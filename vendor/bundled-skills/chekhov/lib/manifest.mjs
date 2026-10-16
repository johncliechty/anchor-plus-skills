/**
 * Managed-file manifest (RIDER 6, ChatGPT M4 order) — W1.
 *
 * Every managed file sits in ONE of TWO classes, SHA-256s recorded at every
 * transition:
 *
 *   1. JOHN'S PROSE — the bible prose, the manuscript and every *_source.md.
 *      He writes these freely in Word or markdown. A change here is EXPECTED:
 *      NEW MATERIAL, printed as `changed since last session: <file>` and
 *      queued for the commit transition — never a violation.
 *
 *   2. ENGINE-OWNED — the outline and beat-sheet markdown, every sidecar
 *      *.ledger.yaml, the decision record, STATUS.json, VERDICTS.md,
 *      session.json and locks/. A change here outside the engine is an
 *      UNMANAGED EDIT and opens a reconciliation HALT.
 *
 * The deny rules chekhov roots writes into each project's .claude/settings.json
 * are DERIVED from these same patterns (one source; the coverage test walks
 * this export).
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const CLASS_PROSE = 'prose';
export const CLASS_ENGINE = 'engine-owned';

/**
 * Pattern table: glob (for the settings deny rules) + matcher (for the walk).
 * *_source.md is ALWAYS John's prose, even when its name also says outline —
 * he writes source files freely; the engine never owns them.
 */
export const MANAGED_PATTERNS = Object.freeze([
  { class: CLASS_PROSE, glob: '**/*_source.md', test: (rel) => /_source\.md$/i.test(rel) },
  { class: CLASS_PROSE, glob: '**/*bible*.md', test: (rel) => /bible[^/]*\.md$/i.test(base(rel)) },
  { class: CLASS_PROSE, glob: '**/*manuscript*.md', test: (rel) => /manuscript[^/]*\.md$/i.test(base(rel)) },
  { class: CLASS_ENGINE, glob: '**/*outline*.md', test: (rel) => /outline[^/]*\.md$/i.test(base(rel)) },
  { class: CLASS_ENGINE, glob: '**/*beat*sheet*.md', test: (rel) => /beat[\s_-]?sheet[^/]*\.md$/i.test(base(rel)) },
  { class: CLASS_ENGINE, glob: '**/*.ledger.yaml', test: (rel) => /\.ledger\.yaml$/i.test(rel) },
  { class: CLASS_ENGINE, glob: '**/DECISIONS.md', test: (rel) => /(^|\/)decisions\.md$/i.test(rel) || /decision[\s_-]?record[^/]*\.md$/i.test(base(rel)) },
  { class: CLASS_ENGINE, glob: '**/STATUS.json', test: (rel) => /(^|\/)status\.json$/i.test(rel) },
  { class: CLASS_ENGINE, glob: '**/VERDICTS.md', test: (rel) => /(^|\/)verdicts\.md$/i.test(rel) },
  { class: CLASS_ENGINE, glob: '**/chekhov/session.json', test: (rel) => /(^|\/)chekhov\/session\.json$/i.test(rel) },
  { class: CLASS_ENGINE, glob: '**/locks/**', test: (rel) => /(^|\/)locks\//i.test(rel) },
]);

function base(rel) {
  const i = rel.lastIndexOf('/');
  return i === -1 ? rel : rel.slice(i + 1);
}

/** Classify a root-relative path (forward slashes) → 'prose' | 'engine-owned' | null. */
export function classifyRel(rel) {
  const norm = String(rel).replace(/\\/g, '/');
  if (/_source\.md$/i.test(norm)) return CLASS_PROSE;
  for (const p of MANAGED_PATTERNS) {
    if (p.class === CLASS_ENGINE && p.test(norm)) return CLASS_ENGINE;
  }
  for (const p of MANAGED_PATTERNS) {
    if (p.class === CLASS_PROSE && p.test(norm)) return CLASS_PROSE;
  }
  return null;
}

export function sha256File(abs) {
  return crypto.createHash('sha256').update(fs.readFileSync(abs)).digest('hex');
}

export function sha256Text(text) {
  return crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');
}

const SKIP_DIRS = new Set(['.git', 'node_modules', '.claude', '.snapshots', '.anchor', '.foreman']);

/**
 * Walk a root and hash every managed file → { schema, files: { rel: { class, sha256 } } }.
 * The engine's own state dir (<root>/chekhov/: session.json, STATUS.json) is
 * NOT walked — the receipt store changes at every append and would otherwise
 * flag itself; its tamper detection is the store's own (generation digest,
 * RIDER 4 waves). The deny rules still cover it via MANAGED_PATTERNS.
 */
export function computeManifest(root) {
  const files = {};
  const committedFile = path.join(root, 'chekhov', 'commit.json');
  const committed = fs.existsSync(committedFile) ? JSON.parse(fs.readFileSync(committedFile, 'utf8')).source_files || [] : [];
  if (!Array.isArray(committed)) throw new Error('commit source_files must be an array');
  const writing = new Set(committed.map(file => String(file).replace(/\\/g, '/')));
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.name.startsWith('.') && SKIP_DIRS.has(e.name)) continue;
      const abs = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name) || e.name === 'chekhov') continue;
        walk(abs);
      } else if (e.isFile()) {
        const rel = path.relative(root, abs).replace(/\\/g, '/');
        const cls = classifyRel(rel) || (writing.has(rel) ? CLASS_PROSE : null);
        if (cls) files[rel] = { class: cls, sha256: sha256File(abs) };
      }
    }
  };
  walk(root);
  return { schema: 'chekhov-manifest-v1', files };
}

/** Deterministic digest of a whole manifest (recorded in every receipt). */
export function manifestHash(manifest) {
  const rels = Object.keys(manifest.files).sort();
  const canon = rels.map((r) => `${r}\t${manifest.files[r].class}\t${manifest.files[r].sha256}`).join('\n');
  return sha256Text(canon);
}

/**
 * Diff two manifests → what changed OUTSIDE the engine.
 *   changed_prose   — John's prose changed: NEW MATERIAL, queued for commit.
 *   unmanaged_engine — engine-owned changed/appeared/vanished outside the
 *                      engine: opens the reconciliation HALT.
 */
export function diffManifests(prev, cur) {
  const changed_prose = [];
  const unmanaged_engine = [];
  const prevFiles = (prev && prev.files) || {};
  const curFiles = (cur && cur.files) || {};
  const all = new Set([...Object.keys(prevFiles), ...Object.keys(curFiles)]);
  for (const rel of [...all].sort()) {
    const a = prevFiles[rel];
    const b = curFiles[rel];
    if (a && b && a.sha256 === b.sha256) continue;
    const cls = (b || a).class;
    if (cls === CLASS_PROSE) changed_prose.push(rel);
    else unmanaged_engine.push(rel);
  }
  return { changed_prose, unmanaged_engine };
}

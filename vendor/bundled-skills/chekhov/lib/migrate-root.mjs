/**
 * lib/migrate-root.mjs — the W2 Bright-Heart migration set.
 *
 * KEEP / CHANGE / DELETE (frozen plan): KEEP every docx (declared stale until
 * Phase 4's render), the existing *_source.md and CLAUDE.md; CHANGE — add the
 * new *_source.md files and chekhov/manifest.json; DELETE nothing. The
 * Artificial Magi root is read-only (its inventory rides along in the
 * manifest for the report).
 *
 * The five canonical Bright-Heart files:
 *   - Series Bible v4.2 Extended — the EXISTING Series_Bible_v4.2_source.md
 *     is kept as canonical when present (hash recorded; divergence from the
 *     docx printed and journaled, never silently overwritten)
 *   - COMPREHENSIVE_CASCADE_SUMMARY.md — already markdown; registered as-is
 *   - CLAUDE.md — registered canonical as-is
 *   - Book_1_Outline_v2 — migrated (an existing _source.md beside it is kept)
 *   - the manuscript (40 chapters as headings) — migrated; its word count is
 *     recorded under the ONE rule with the prior tool's 167,412 beside it,
 *     reference only.
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  migrateDocx,
  convertDocx,
  sha256Bytes,
  stripMigrationHeader,
  migrationHeader,
  dateForDocx,
  recordDivergence,
} from './migrate.mjs';
import { manuscriptWordcount } from './wordcount.mjs';
import { amInventory } from './inventory.mjs';

export const ROOT_MANIFEST_SCHEMA = 'chekhov-root-manifest-v1';

/** The prior tool's manuscript figure — recorded for reference only. */
export const PRIOR_TOOL_FIGURE = 167412;

/** The named W2 set, root-relative (roots.json fixes the absolute root). */
export const BH_MIGRATION_SET = Object.freeze([
  Object.freeze({
    id: 'bh.series-bible-v4.2-extended',
    kind: 'docx',
    rel: 'Rework 2026/Revision/Series_Bible_v4.2_Extended.docx',
    canonical_rel: 'Rework 2026/Revision/Series_Bible_v4.2_source.md',
  }),
  Object.freeze({ id: 'bh.cascade-summary', kind: 'markdown', rel: 'COMPREHENSIVE_CASCADE_SUMMARY.md' }),
  Object.freeze({ id: 'bh.claude-md', kind: 'markdown', rel: 'CLAUDE.md' }),
  Object.freeze({ id: 'bh.book1-outline-v2', kind: 'docx', rel: 'Rework 2026/Book_1_Outline_v2.docx' }),
  Object.freeze({
    id: 'bh.manuscript',
    kind: 'docx',
    rel: 'Rework 2026/Starting Materials/Bright-Heart Start 2026.docx',
    manuscript: true,
  }),
]);

export function rootManifestPath(rootPath) {
  return path.join(rootPath, 'chekhov', 'manifest.json');
}

/**
 * Migrate one NAMED set into a root and write <root>/chekhov/manifest.json.
 * Idempotent: existing *_source.md files are kept (divergence reported, never
 * overwritten); re-running on unchanged inputs rewrites the same manifest.
 */
export async function migrateNamedSet(rootPath, set, opts = {}) {
  const lines = [];
  const canonical = [];
  let ok = true;
  let wordcount = null;

  for (const entry of set) {
    const abs = path.join(rootPath, entry.rel);
    if (!fs.existsSync(abs)) {
      ok = false;
      lines.push(`MISSING: ${entry.rel}`);
      canonical.push({ id: entry.id, rel: entry.rel, status: 'missing', sha256: null });
      continue;
    }

    if (entry.kind === 'markdown') {
      // Already canonical in form: registered as-is, hash recorded.
      canonical.push({
        id: entry.id,
        rel: entry.rel,
        status: 'canonical',
        action: 'registered-as-is',
        sha256: sha256Bytes(fs.readFileSync(abs)),
      });
      lines.push(`registered canonical as-is: ${entry.rel}`);
      continue;
    }

    if (entry.canonical_rel && fs.existsSync(path.join(rootPath, entry.canonical_rel))) {
      // The existing canonical markdown carries its own name: KEEP it, hash
      // it, and report divergence from a fresh conversion of the docx.
      const canonAbs = path.join(rootPath, entry.canonical_rel);
      const { body } = await convertDocx(abs);
      const docxSha = sha256Bytes(fs.readFileSync(abs));
      const existing = fs.readFileSync(canonAbs, 'utf8');
      const diverged = stripMigrationHeader(existing).trim() !== body.trim();
      canonical.push({
        id: entry.id,
        rel: entry.canonical_rel,
        status: 'canonical',
        action: 'kept-existing-canonical',
        sha256: sha256Bytes(fs.readFileSync(canonAbs)),
        source_docx: entry.rel,
        source_docx_sha256: docxSha,
        date: dateForDocx(abs),
        diverged,
      });
      lines.push(`kept existing canonical: ${entry.canonical_rel}`);
      if (diverged) lines.push(recordDivergence({ canonicalPath: canonAbs, docxPath: abs, journalPath: opts.journalPath }));
      continue;
    }

    // Plain docx migration (writes <name>_source.md, or keeps an existing one).
    const out = await migrateDocx(abs, { journalPath: opts.journalPath });
    if (!out.ok) {
      ok = false;
      lines.push(out.error);
      continue;
    }
    const rel = path.relative(rootPath, out.outPath).replace(/\\/g, '/');
    canonical.push({
      id: entry.id,
      rel,
      status: 'canonical',
      action: out.action,
      sha256: out.source_sha256,
      source_docx: entry.rel,
      source_docx_sha256: out.docx_sha256,
      date: dateForDocx(abs),
      diverged: out.diverged,
    });
    lines.push(...out.lines);

    if (entry.manuscript) {
      const markdown = fs.readFileSync(out.outPath, 'utf8');
      wordcount = manuscriptWordcount(markdown, { priorFigure: opts.priorFigure ?? PRIOR_TOOL_FIGURE });
      wordcount.manuscript_rel = rel;
      lines.push(
        `manuscript word count (the one rule): ${wordcount.total} across ${wordcount.chapters.length} chapters`
        + ` (prior tool: ${wordcount.prior_tool_figure}, reference only)`,
      );
    }
  }

  const manifest = {
    schema: ROOT_MANIFEST_SCHEMA,
    root: opts.rootId || 'bright-heart',
    canonical,
    wordcount,
  };
  if (opts.amRootPath && fs.existsSync(opts.amRootPath)) {
    manifest.am_inventory = amInventory(opts.amRootPath);
  }
  const target = rootManifestPath(rootPath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  lines.push(`manifest: ${path.relative(rootPath, target).replace(/\\/g, '/')}`);

  return { ok, lines, manifest, manifestPath: target };
}

/** The W2 deliverable: the Bright-Heart named set into the bright-heart root. */
export function migrateBrightHeartRoot(rootPath, opts = {}) {
  return migrateNamedSet(rootPath, BH_MIGRATION_SET, { rootId: 'bright-heart', ...opts });
}

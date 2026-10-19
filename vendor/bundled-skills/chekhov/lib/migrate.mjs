/**
 * chekhov migrate <docx> — W2.
 *
 * Writes <name>_source.md beside the docx (headings and paragraphs preserved),
 * DETERMINISTIC — the same input file yields the same bytes — with a header
 * comment recording the source file, its SHA-256 and a date. The date is
 * derived from the docx file's mtime (UTC, YYYY-MM-DD), never from the wall
 * clock, so re-running on the same input reproduces the file byte for byte.
 *
 * needed-because: mammoth (pinned) converts OOXML; writing that parser
 * in-house is a reinvention (frozen plan, W2).
 *
 * An EXISTING <name>_source.md is KEPT as canonical — never silently
 * overwritten. Divergence between the existing markdown and a fresh
 * conversion of the docx is reported (the caller prints it) and appended to
 * the journal when a journalPath is given.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const HEADER_MARKER = 'chekhov:migrated';

export function sha256Bytes(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

/** <dir>/<name>.docx → <dir>/<name>_source.md */
export function sourcePathFor(docxPath) {
  const dir = path.dirname(docxPath);
  const name = path.basename(docxPath).replace(/\.docx$/i, '');
  return path.join(dir, `${name}_source.md`);
}

/** Date recorded in the header: the docx mtime (UTC) — deterministic per input. */
export function dateForDocx(docxPath) {
  return new Date(fs.statSync(docxPath).mtimeMs).toISOString().slice(0, 10);
}

/** The header comment: source file, SHA-256, date. Ends with a blank line. */
export function migrationHeader({ sourceName, sha256, date }) {
  return [
    `<!-- ${HEADER_MARKER}`,
    `  source: ${sourceName}`,
    `  source_sha256: ${sha256}`,
    `  date: ${date}`,
    '-->',
    '',
    '',
  ].join('\n');
}

/** Remove the leading chekhov:migrated header comment, if present. */
export function stripMigrationHeader(text) {
  const s = String(text);
  if (!s.startsWith(`<!-- ${HEADER_MARKER}`)) return s;
  const end = s.indexOf('-->');
  return end === -1 ? s : s.slice(end + 3).replace(/^\n+/, '');
}

/** Parse the header fields back out of a migrated file's text. */
export function parseMigrationHeader(text) {
  const s = String(text);
  if (!s.startsWith(`<!-- ${HEADER_MARKER}`)) return null;
  const block = s.slice(0, s.indexOf('-->'));
  const field = (name) => {
    const m = block.match(new RegExp(`^\\s*${name}: (.*)$`, 'm'));
    return m ? m[1].trim() : null;
  };
  return { source: field('source'), source_sha256: field('source_sha256'), date: field('date') };
}

/**
 * Convert one docx to markdown via mammoth (lazy import: only migrate pays
 * for the dependency). mammoth's empty bookmark anchors are stripped — pure
 * noise in a source file; headings and paragraphs pass through untouched.
 * Embedded images never inline as base64 (the roots are TEXT-only, W1): a
 * small deterministic placeholder records that an image sits in the docx.
 */
export async function convertDocx(docxPath) {
  const mammoth = await import('mammoth');
  const result = await mammoth.convertToMarkdown(
    { path: docxPath },
    { convertImage: mammoth.images.imgElement(async (image) => ({ src: `docx-image:${image.contentType}` })) },
  );
  let body = result.value.replace(/<a id="[^"]*"><\/a>/g, '');
  if (!body.endsWith('\n')) body += '\n';
  return { body, messages: result.messages };
}

/**
 * One divergence line, printed by callers and appended to the journal.
 * Idempotent: a line already in the journal is not appended twice.
 */
export function recordDivergence({ canonicalPath, docxPath, journalPath }) {
  const line = `- DIVERGENCE: ${path.basename(canonicalPath)} (kept as canonical) differs from a fresh conversion of ${path.basename(docxPath)} — never silently overwritten; reconcile at a decision sitting.`;
  if (journalPath) {
    try {
      const existing = fs.existsSync(journalPath) ? fs.readFileSync(journalPath, 'utf8') : '';
      if (!existing.includes(line)) fs.appendFileSync(journalPath, `${line}\n`, 'utf8');
    } catch {
      /* journal missing: the divergence still reaches the caller's print */
    }
  }
  return line;
}

/**
 * Migrate one docx → <name>_source.md beside it.
 *
 * Returns { ok, action: 'written' | 'kept-existing', outPath, docx_sha256,
 * source_sha256, diverged?, lines }. `lines` is what the CLI prints.
 */
export async function migrateDocx(docxPath, opts = {}) {
  const abs = path.resolve(docxPath);
  if (!fs.existsSync(abs) || !/\.docx$/i.test(abs)) {
    return { ok: false, error: `not a docx on disk: ${docxPath}`, lines: [`not a docx on disk: ${docxPath}`] };
  }
  const docxSha = sha256Bytes(fs.readFileSync(abs));
  const outPath = sourcePathFor(abs);
  const { body } = await convertDocx(abs);
  const header = migrationHeader({ sourceName: path.basename(abs), sha256: docxSha, date: dateForDocx(abs) });
  const text = header + body;

  if (fs.existsSync(outPath)) {
    // KEPT as canonical — never silently overwritten.
    const existing = fs.readFileSync(outPath, 'utf8');
    const diverged = stripMigrationHeader(existing).trim() !== stripMigrationHeader(text).trim();
    const lines = [`kept existing: ${path.basename(outPath)} (canonical; the docx was not rendered over it)`];
    if (diverged) lines.push(recordDivergence({ canonicalPath: outPath, docxPath: abs, journalPath: opts.journalPath }));
    return {
      ok: true,
      action: 'kept-existing',
      outPath,
      docx_sha256: docxSha,
      source_sha256: sha256Bytes(fs.readFileSync(outPath)),
      diverged,
      lines,
    };
  }

  fs.writeFileSync(outPath, text, 'utf8');
  return {
    ok: true,
    action: 'written',
    outPath,
    docx_sha256: docxSha,
    source_sha256: sha256Bytes(Buffer.from(text, 'utf8')),
    diverged: false,
    lines: [`migrated: ${path.basename(abs)} → ${path.basename(outPath)}`],
  };
}

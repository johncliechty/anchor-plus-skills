/**
 * Vendor John's verbatim BA 815 description (Appendix A) as a test fixture.
 *
 * WHY VENDOR IT AT ALL. The acceptance criterion is that the steward is proven against
 * JOHN'S OWN WRITING, not a sentence an implementer chose — every failure this week came
 * from a test picking its own convenient input. Reading the brief live would make the
 * suite depend on a file outside the repo; retyping it would let it drift into something
 * easier. So it is copied verbatim, and a test asserts the copy still matches the source
 * whenever the source is present.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const FIXTURE_REL = path.join('test', 'fixtures', 'ba815-appendix-a.txt');
export const SOURCE_BRIEF = path.join('C:', 'dev', 'MBA Teaching AI', 'COURSE-REVAMP-BRIEF.md');

/**
 * Extract the blockquoted verbatim text between the Appendix A and Appendix B headings.
 * @param {string} markdown
 * @returns {string}
 */
export function extractAppendixA(markdown) {
  const afterA = String(markdown).split('## Appendix A')[1];
  if (!afterA) return '';
  const body = afterA.split('## Appendix B')[0];
  return body
    .split(/\r?\n/)
    .filter((l) => l.trim().startsWith('>'))
    .map((l) => l.replace(/^\s*>\s?/, ''))
    .join(' ')
    .trim();
}

if (process.argv[1] && process.argv[1].endsWith('vendor-appendix-a.mjs')) {
  const src = process.argv[2] ?? SOURCE_BRIEF;
  const md = fs.readFileSync(src, 'utf8');
  const text = extractAppendixA(md);
  if (!text) throw new Error(`No Appendix A blockquote found in ${src}`);
  const out = path.join(ROOT, FIXTURE_REL);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, text, 'utf8');
  process.stdout.write(`${text.length} chars -> ${FIXTURE_REL}\n`);
}

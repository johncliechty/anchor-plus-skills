/** W5: full planning prose and structural entries; never manuscript narrative. */
import fs from 'node:fs';
import { effectiveAllowTerms } from './tuples.mjs';
import { fold, markdownRows, projectDocuments } from './prose.mjs';

const doctrineData = JSON.parse(fs.readFileSync(new URL('../packs/doctrine-lint.json', import.meta.url), 'utf8'));
export const DOCTRINE_TERMS = Object.freeze(doctrineData.terms);
const COLLISIONS = new Set(doctrineData.collisions_whitelisted);
const REPUDIATED_VERSION_NOTE = new RegExp(doctrineData.repudiation.version_note_pattern, 'i');
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function beatContext(row, term, structural) {
  if (structural) return true;
  const text = fold(row.text).replace(/[*_]/g, '');
  const heading = fold(row.heading || '').replace(/[*_]/g, '').trim();
  if (heading === term || new RegExp(`^${escape(term)}\\s*(?:[(:—–-]|phase|beat)`).test(heading)) return true;
  return (new RegExp(`\\b(?:beat|phase|doctrine|structure|movement)\\s*(?:name\\s*)?[:=—–-]?\\s*${escape(term)}\\b|\\b${escape(term)}\\s+(?:beat|phase|structure)\\b`).test(text)
    || (term === 'ten' && /\b(?:at the ten|the ten is|the ten of)\b/.test(text)))
    && !(term === 'ten' && /\bten\s+(?:books|chapters|years|days|people|words)\b/.test(text));
}

export function scanDoctrine(documents, { tag, decisions = [], structural = [] } = {}) {
  const own = fold(tag || '').replace(/\s+/g, '-');
  const allow = new Set(decisions.flatMap(effectiveAllowTerms).map(fold));
  const hits = [];
  const ignored = [];
  const inspect = (doc, row, isStructural = false) => {
    const text = fold(row.text);
    for (const [family, terms] of Object.entries(DOCTRINE_TERMS)) {
      if (family === own) continue;
      for (const term of terms) {
        if (!new RegExp(`\\b${escape(term)}\\b`, 'i').test(text)) continue;
        const hit = { doctrine: family, term, file: doc.file, line: row.line, heading_path: row.heading_path, span: row.text };
        if (allow.has(term)) { ignored.push({ ...hit, reason: 'locked decision allow_terms' }); continue; }
        // A quoted repudiation describes a rejected doctrine, not a license to use it.
        const correction = /^(?:\*\*)?Correction of record\b/i.test(row.text.trim()) && /was an error and is repudiated/i.test(row.text);
        const versionNote = /^v\d+(?:\.\d+)+\s*[—–-]/i.test(row.text.trim()) && REPUDIATED_VERSION_NOTE.test(row.text);
        if ((correction || versionNote) && family === doctrineData.repudiation.family) {
          ignored.push({ ...hit, reason: 'explicit repudiation' }); continue;
        }
        if (COLLISIONS.has(term) && !beatContext(row, term, isStructural)) {
          ignored.push({ ...hit, reason: 'ordinary-English collision' }); continue;
        }
        hits.push(hit);
      }
    }
  };
  for (const doc of documents) {
    if (doc.kind === 'manuscript') continue;
    for (const row of markdownRows(doc.text)) inspect(doc, row);
  }
  for (const entry of structural) {
    const source = { file: entry.sidecar || 'structural record' };
    const row = { line: entry.receipt?.line_hint ?? null, heading_path: entry.receipt?.heading_path || [entry.id] };
    inspect(source, { ...row, text: String(entry.value.beat) }, true);
    for (const [key, value] of Object.entries(entry.value)) {
      if (key !== 'beat' && typeof value === 'string') inspect(source, { ...row, text: value });
    }
  }
  return { tag: own || null, hits, ignored, files_read: documents.filter((d) => d.kind !== 'manuscript').map((d) => d.file) };
}

export function doctrineForRoot(root, options = {}) {
  const documents = projectDocuments(root, { read: options.read });
  return scanDoctrine(documents, options);
}

/** Span-level precision/recall: expectations are independently labelled before scoring. */
export function measureDoctrine(fixtures, options) {
  let tp = 0, fp = 0, fn = 0;
  for (const fixture of fixtures) {
    const actual = new Set(scanDoctrine([fixture], options).hits.map((h) => `${h.line}:${h.term}`));
    const expected = new Set(fixture.expected.map((h) => `${h.line}:${h.term}`));
    for (const key of actual) expected.has(key) ? tp++ : fp++;
    for (const key of expected) if (!actual.has(key)) fn++;
  }
  return { tp, fp, fn, precision: tp + fp ? tp / (tp + fp) : null, recall: tp + fn ? tp / (tp + fn) : null };
}

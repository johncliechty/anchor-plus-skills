/** W5: markdown evidence is read independently of sidecar claims. */
import fs from 'node:fs';
import path from 'node:path';

const doctrineData = JSON.parse(fs.readFileSync(new URL('../packs/doctrine-lint.json', import.meta.url), 'utf8'));

export const PROSE_IDS = Object.freeze(['series.book_count', 'series.chapter_rule', 'series.doctrine_tag']);
export const fold = (s) => String(s).normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

// Archived skill text is never runtime prose, even if a manifest names it.
const frozenSkillPath = (rel) => /(?:^|\/)(?:skills|\.claude)(?:\/|$)/i.test(rel.replace(/\\/g, '/'));

/** Path classification precedes reads; an inventoried manuscript wins over its filename. */
export function proseClass(rel, entry = {}) {
  const name = rel.replace(/\\/g, '/');
  if (entry.manuscript || /manuscript/i.test(entry.id || '') || /manuscript|\/chapters?\//i.test(name)) return 'manuscript';
  if (/bible|appendi[xc]|outline|beat[ _-]?sheet|spine|cascade|(^|\/)CLAUDE\.md$/i.test(name)) return 'doctrine';
  return null;
}

export function projectDocuments(root, { manuscripts = false, read = (file) => fs.readFileSync(file, 'utf8') } = {}) {
  const manifestFile = path.join(root, 'chekhov', 'manifest.json');
  const manifest = fs.existsSync(manifestFile) ? JSON.parse(read(manifestFile)) : {};
  const registry = new Map((manifest.canonical || []).filter((e) => !frozenSkillPath(e.rel)).map((e) => [e.rel.replace(/\\/g, '/'), e]));
  const canonicalBible = [...registry.keys()].some((rel) => /bible/i.test(path.basename(rel)));
  const paths = new Set(registry.keys());
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name.startsWith('.') || e.name === 'node_modules' || e.name === 'chekhov' || frozenSkillPath(e.name)) continue;
      const file = path.join(dir, e.name);
      if (e.isDirectory()) walk(file);
      else if (e.isFile() && /\.md$/i.test(e.name)) paths.add(path.relative(root, file).replace(/\\/g, '/'));
    }
  };
  walk(root);
  return [...paths].sort().flatMap((rel) => {
    const entry = registry.get(rel) || {};
    const kind = proseClass(rel, entry);
    if (!kind || (kind === 'manuscript') !== manuscripts || entry.status === 'missing') return [];
    // When a canonical bible exists, keep its older versions out of live truth.
    if (kind !== 'manuscript' && !registry.has(rel) && canonicalBible && /bible/i.test(path.basename(rel))) return [];
    return [{ file: rel, kind, entry, text: read(path.join(root, rel)) }];
  });
}

/** ATX, Setext and bold heading lines retain their original one-based line. */
export function markdownRows(text) {
  const lines = String(text).split(/\r?\n/);
  const stack = [];
  let fenced = false;
  let comment = false;
  return lines.map((raw, i) => {
    if (/^\s*(```|~~~)/.test(raw)) { fenced = !fenced; return null; }
    if (raw.includes('<!--')) comment = true;
    if (comment) { if (raw.includes('-->')) comment = false; return null; }
    if (fenced) return null;
    const atx = /^(#{1,6})\s+(.+?)\s*#*$/.exec(raw);
    const setext = i + 1 < lines.length && /^\s*(={3,}|-{3,})\s*$/.test(lines[i + 1]) && raw.trim() && !raw.includes('|');
    const bold = /^\s*\*\*(.+?)\*\*\s*:?(.*)$/.exec(raw);
    let heading = null;
    let level = 0;
    if (atx) { level = atx[1].length; heading = atx[2]; }
    else if (setext) { level = lines[i + 1].trim()[0] === '=' ? 1 : 2; heading = raw.trim(); }
    else if (bold) { level = 6; heading = bold[1]; }
    if (heading) { stack.length = level - 1; stack[level - 1] = heading.replace(/[*_]/g, ''); }
    return { text: raw, line: i + 1, heading_path: stack.filter(Boolean), heading };
  }).filter(Boolean);
}

const NUMBER_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'];
const BOOK_NUMBER = `(?:\\d+|${NUMBER_WORDS.slice(1).join('|')})`;
const LENGTH = '(\\d[\\d,]*(?:\\.\\d+)?\\s*[kK]?)(?:\\s*(?:--?|[–—]|to)\\s*(\\d[\\d,]*(?:\\.\\d+)?\\s*[kK]?))?';
export const bookCount = (s) => NUMBER_WORDS.includes(fold(s).trim()) ? NUMBER_WORDS.indexOf(fold(s).trim()) : Number(s);
const wordsValue = (s, thousand = false) => Number(s.replace(/[,\s kK]/g, '')) * (/[kK]/.test(s) || thousand ? 1000 : 1);

export function chapterRule(value) {
  if (value && typeof value === 'object') {
    const min = Number(value.min ?? value.min_words);
    const max = Number(value.max ?? value.max_words ?? min);
    return min > 0 && max >= min ? { min, max } : null;
  }
  const match = new RegExp(LENGTH).exec(String(value));
  if (!match) return null;
  const min = wordsValue(match[1], Boolean(match[2] && /k/i.test(match[2]) && !/k/i.test(match[1])));
  const max = match[2] ? wordsValue(match[2]) : min;
  return min > 0 && max >= min ? { min, max } : null;
}

export function scanProse(documents) {
  const hits = [];
  const seen = new Set();
  const add = (doc, row, id, value, span, extra = {}) => {
    const key = JSON.stringify([doc.file, row.line, id, value]);
    if (seen.has(key)) return;
    seen.add(key);
    hits.push({ id, value, span, file: doc.file, line: row.line, heading_path: row.heading_path, ...extra });
  };
  for (const doc of documents) {
    let chapter = null;
    for (const row of markdownRows(doc.text)) {
      const text = row.text.replace(/[*_]/g, '');
      const c = /\b(?:chapter|ch\.)\s*(\d+)\b/i.exec(row.heading || text);
      if (c) chapter = Number(c[1]);
      for (const m of text.matchAll(new RegExp(`\\b(${BOOK_NUMBER})[ –—‑-]+books?\\b`, 'gi'))) {
        // A single physical book isn't a series-size declaration.
        if (/\bseries\b|\barc\b|architecture|across all|books\b|[–—‑-]book/i.test(text)) add(doc, row, PROSE_IDS[0], bookCount(m[1]), m[0]);
      }
      for (const m of text.matchAll(new RegExp(`\\b(?:series\\s*(?:of|:|=|has|contains|comprises|runs to)|book[ -]count\\s*[:=]|books\\s*[:=])\\s*(${BOOK_NUMBER})\\b`, 'gi'))) add(doc, row, PROSE_IDS[0], bookCount(m[1]), m[0]);
      const chapterContext = chapter !== null || /chapter|ch\.|word count|word length/i.test(text + ' ' + row.heading_path.join(' '));
      if (chapterContext) {
        for (const m of text.matchAll(new RegExp(LENGTH, 'g'))) {
          const rule = chapterRule(m[0]);
          if (!rule) continue;
          const before = text.slice(0, m.index);
          const after = text.slice(m.index + m[0].length);
          const unit = /^\s*[-–]?\s*words?\b/i.test(after);
          // A word-count heading also contains chapter coordinates and counts.
          // Their own unit wins over the surrounding heading; the numeric
          // match may already have consumed trailing whitespace.
          const chapterPosition = /\b(?:chapters?|chs?\.?)\s*$/i.test(before)
            || /^\s*(?:chapters?\b|chs?\.(?=\s|\||$))/i.test(after);
          if (chapterPosition && !unit) continue;
          const target = /(?:expand(?:ed|sion)?(?:\s+to)?|target|chapter[- ]length|length)[:\s~=-]*$/i.test(before);
          const field = !row.heading && /word count|chapter.*rule/i.test(row.heading_path.at(-1) || '') && !/^\s*(?:chapter|date)\b/i.test(text);
          if (!unit && !target && !field) continue;
          add(doc, row, PROSE_IDS[1], rule, m[0], { chapter, role: /rule|per chapter|chapter length|chapters? (?:at|of|should|must)|words? each/i.test(text + ' ' + row.heading_path.join(' ')) ? 'rule' : 'chapter-length' });
        }
      }
      if (row.heading) {
        for (const [term, value] of doctrineData.heading_terms) {
          if (new RegExp(`\\b${term}\\b`).test(fold(row.heading))) add(doc, row, PROSE_IDS[2], value, row.heading);
        }
      }
    }
  }
  const values = Object.fromEntries(PROSE_IDS.map((id) => [id, [...new Map(hits.filter((h) => h.id === id).map((h) => [JSON.stringify(h.value), h.value])).values()]]));
  const contradictions = PROSE_IDS.filter((id) => values[id].length > 1).map((id) => ({ claim: id, values: values[id], comparator: 'prose-single-value', spans: hits.filter((h) => h.id === id) }));
  return { hits, values, contradictions, single_valued: PROSE_IDS.every((id) => values[id].length === 1) };
}

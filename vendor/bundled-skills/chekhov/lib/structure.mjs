/** W5 structural record is a report preview. Commit fills candidates; accept locks. */
import { manuscriptWordcount } from './wordcount.mjs';
import { chapterRule, markdownRows } from './prose.mjs';
import { decisionValues } from './asks.brightheart.mjs';

export function chapterBreaches(documents, rules) {
  const parsed = [...new Map(rules.map(chapterRule).filter(Boolean).map((r) => [JSON.stringify(r), r])).values()];
  const counts = documents.flatMap((doc) => manuscriptWordcount(doc.text).chapters.map((c) => ({ ...c, file: doc.file })));
  return { counts, rules: parsed, unknown: parsed.length === 0,
    breaches: counts.flatMap((c) => parsed.filter((r) => c.words < r.min || c.words > r.max).map((rule) => ({ ...c, rule }))) };
}

export function buildStructuralRecord({ pack, documents = [], manuscripts = [], tuples = [], prose } = {}) {
  const decisions = tuples.filter((t) => t.kind === 'decision');
  const ruleValues = decisionValues(decisions, 'series.chapter_rule');
  const factRules = tuples.filter((t) => t.kind === 'fact' && t.interval.scope !== 'unspecified' && t.value?.entity === 'series' && t.value?.predicate === 'chapter_rule').map((t) => t.value.object);
  const proseRules = (prose?.hits || []).filter((h) => h.id === 'series.chapter_rule' && h.role === 'rule').map((h) => h.value);
  const wordcounts = chapterBreaches(manuscripts, ruleValues.length ? ruleValues : factRules.length ? factRules : proseRules);
  const candidates = [];
  for (const [index, doc] of manuscripts.entries()) {
    const book = Number(doc.entry?.book || /\bbook[ _-]?(\d+)/i.exec(doc.file)?.[1] || 1);
    const rows = markdownRows(doc.text);
    for (const c of wordcounts.counts.filter((r) => r.file === doc.file)) {
      const row = rows.find((r) => r.heading === c.heading);
      candidates.push({ schema: 1, id: `structure.b${book}.m${index + 1}.ch${c.chapter}.word_count`, kind: 'structural', lock: 'candidate',
        value: { beat: 'chapter_word_count', position: c.chapter, words: c.words }, interval: { from: `${book}.${c.chapter}`, to: `${book}.${c.chapter}` },
        receipt: { span: row?.text || c.heading, heading_path: row?.heading_path || [c.heading], line_hint: row?.line || 1, date: doc.entry?.date || null },
        source_file: doc.file });
    }
  }
  const chosen = decisionValues(decisions, 'series.book_count');
  const observed = (prose?.values?.['series.book_count'] || []).filter((n) => Number.isInteger(n) && n > 0);
  const books = chosen.length === 1 ? Array.from({ length: chosen[0] }, (_, i) => i + 1)
    : observed.length ? Array.from({ length: Math.max(...observed) }, (_, i) => i + 1) : pack.default_orders?.reader_order || [1];
  const beats = pack.beat_table?.per_book.filter((b) => b.structural) || (pack.beats || []).map((name, i) => ({ name, position: i + 1 }));
  const slots = books.flatMap((book) => beats.map((beat) => {
    const entries = tuples.filter((t) => t.kind === 'structural' && !t.interval.scope && t.value?.beat === beat.name && Number(t.interval.from.split('.')[0]) === book);
    return { book, beat: beat.name, position: beat.position, entries, state: entries.length ? 'filled' : 'unfilled — commit candidate, accept to lock' };
  }));
  const cuts = documents.flatMap((doc) => markdownRows(doc.text).filter((r) => /\btriumph(?:ant)?\b|\b(?:earned )?victory\b/i.test(r.text)).map((r) => ({ file: doc.file, line: r.line, heading_path: r.heading_path, span: r.text })));
  const outlineBreaches = (prose?.hits || []).filter((h) => h.id === 'series.chapter_rule' && h.chapter && /outline/i.test(h.file)).flatMap((h) => wordcounts.rules.filter((r) => h.value.min < r.min || h.value.max > r.max).map((rule) => ({ ...h, rule })));
  const unplaced = tuples.filter(t => t.kind === 'structural' && t.interval.scope);
  return { candidates, slots, unplaced, cuts, wordcounts, outline_breaches: outlineBreaches, checklist: [
    'Cut after a triumph: review each cited candidate for an earned local victory and a complete Book 1 promise.',
    'Duology kill-gate: reject a split unless BOTH volumes have a complete promise, turn and closure; reject a cut that only postpones Book 1 payoff.',
    ...(pack.checklist || []),
  ] };
}

export function renderStructure(record) {
  const lines = ['Structural candidates (report preview; no acceptance implied):'];
  for (const t of record.unplaced || []) lines.push(`- ${t.id} [${t.lock}]: ${JSON.stringify(t.value)} — ${t.interval.scope} scope, unplaced; "${t.receipt.span}"`);
  for (const c of record.candidates) lines.push(`- ${c.id}: ${c.value.words} words; candidate (${c.source_file}, line ${c.receipt.line_hint})`);
  for (const s of record.slots) lines.push(`- Book ${s.book} ${s.beat} (position ${s.position}): ${s.entries.length ? s.entries.map((e) => `${e.id} [${e.lock}]`).join(', ') : s.state}`);
  lines.push('Chapter breaches:');
  if (record.wordcounts.unknown) lines.push('- chapter_rule unknown — counts listed without a guessed length target');
  if (!record.wordcounts.breaches.length && !record.outline_breaches.length) lines.push('- none');
  for (const b of record.wordcounts.breaches) lines.push(`- ${b.file}, Chapter ${b.chapter}: ${b.words} words outside ${b.rule.min}–${b.rule.max}`);
  for (const b of record.outline_breaches) lines.push(`- ${b.file}, ${b.heading_path.join(' > ')}, line ${b.line}: Chapter ${b.chapter} ${b.span} outside ${b.rule.min}–${b.rule.max}`);
  lines.push('Cut-after-a-triumph candidates:');
  if (!record.cuts.length) lines.push('- none found; no boundary inferred');
  for (const c of record.cuts) lines.push(`- [ ] ${c.file}, ${c.heading_path.join(' > ')}, line ${c.line}: ${c.span}`);
  for (const item of record.checklist) lines.push(`- [ ] ${item}`);
  return lines;
}

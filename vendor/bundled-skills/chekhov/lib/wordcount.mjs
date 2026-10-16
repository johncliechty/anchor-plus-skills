/**
 * lib/wordcount.mjs — THE one counting rule (W2).
 *
 * THE RULE: strip the chekhov:migrated header comment; split the remaining
 * text on Unicode whitespace; a token counts as ONE word iff it contains at
 * least one letter or digit (so "Ristlyng's", "J\.C\." and "40" each count 1;
 * a bare em-dash, "***" or "-->" counts 0). Heading lines count their words.
 *
 * No other tool's rule is consulted. The prior tool's figure (167,412 for the
 * Bright-Heart manuscript) is recorded BESIDE this rule's output for reference
 * only — there is no 1% reconciliation target; chapter breaches are judged
 * under THIS rule (verification round).
 */
import { stripMigrationHeader } from './migrate.mjs';

export const COUNTING_RULE =
  'split on Unicode whitespace after stripping the chekhov:migrated header comment; '
  + 'a token counts as one word iff it contains at least one letter or digit; '
  + 'heading lines count their words';

/** Count words under THE rule. */
export function countWords(text) {
  let n = 0;
  for (const tok of stripMigrationHeader(text).split(/\s+/u)) {
    if (/[\p{L}\p{N}]/u.test(tok)) n += 1;
  }
  return n;
}

const HEADING_RE = /^(#{1,6})\s*(.*)$/;
const CHAPTER_RE = /^chapter\s+(\d+)\b/i;

/**
 * Partition a manuscript's lines into front-matter + chapter segments.
 * A segment starts at a heading line (any level) whose text begins
 * "Chapter <n>" and runs to the next such heading or EOF — so a trailing
 * "THE END" heading belongs to the last chapter. Because the segments
 * PARTITION the lines, the segment word counts always sum to the whole
 * document's count under the same rule.
 */
export function segmentByChapters(markdown) {
  const lines = stripMigrationHeader(markdown).split('\n');
  const segments = [];
  let cur = { kind: 'front-matter', heading: 'front-matter', chapter: null, lines: [] };
  for (const line of lines) {
    const h = line.match(HEADING_RE);
    const c = h ? h[2].match(CHAPTER_RE) : null;
    if (c) {
      segments.push(cur);
      cur = { kind: 'chapter', heading: h[2].trim(), chapter: Number(c[1]), lines: [] };
    }
    cur.lines.push(line);
  }
  segments.push(cur);
  return segments;
}

/**
 * The manuscript record written into <root>/chekhov/manifest.json:
 * total and per-chapter counts under THE rule, with the prior tool's figure
 * beside them for reference only.
 */
export function manuscriptWordcount(markdown, { priorFigure } = {}) {
  const segments = segmentByChapters(markdown);
  const chapters = segments
    .filter((s) => s.kind === 'chapter')
    .map((s) => ({ chapter: s.chapter, heading: s.heading, words: countWords(s.lines.join('\n')) }));
  const frontMatterWords = segments
    .filter((s) => s.kind === 'front-matter')
    .reduce((n, s) => n + countWords(s.lines.join('\n')), 0);
  const total = countWords(markdown);
  return {
    rule: COUNTING_RULE,
    total,
    front_matter_words: frontMatterWords,
    chapters,
    prior_tool_figure: priorFigure ?? null,
    prior_tool_note: 'reference only — no reconciliation target; chapter breaches are judged under the one rule',
  };
}

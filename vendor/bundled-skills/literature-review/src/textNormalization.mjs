// Wave 3 — exact text normalization for verbatim-quote grounding.
// One canonical normal form is applied to BOTH the source text and every
// candidate quote, so grounding is a strict exact-string match:
//   1. Unicode NFKC (compatibility ligatures, full-width forms, superscripts);
//   2. case-folding (Unicode lowercase);
//   3. whitespace consolidation (any run of Unicode whitespace -> one space,
//      leading/trailing runs dropped);
//   4. default-ignorable format characters (Cf: ZWSP, soft hyphen, BOM) are
//      stripped — they are invisible, so "erratic" copies must still match.
// buildNormalizedView additionally keeps a per-character offset map back into
// the raw source, so any match found in normalized space can be traced to the
// exact verbatim raw span — the unbroken evidence lineage the North Star
// demands. Normalization is applied per combining-mark segment (base code
// point plus trailing marks), which keeps the map byte-precise while still
// composing sequences like `e` + U+0301 into `é`.

const COMBINING_MARK_RE = /\p{M}/u;
const FORMAT_CHAR_RE = /\p{Cf}/u;
const WHITESPACE_RE = /\s/u;

function isCombiningMark(cp) {
  return COMBINING_MARK_RE.test(String.fromCodePoint(cp));
}

/**
 * Normalize `raw` and keep the offset map.
 *
 * @param {string} raw
 * @returns {{source: string, text: string, starts: number[], ends: number[]}}
 *   `text` is the normalized string; for normalized char k, `starts[k]` /
 *   `ends[k]` bound the raw slice that produced it (a collapsed whitespace
 *   char maps to its whole raw whitespace run).
 */
export function buildNormalizedView(raw) {
  const source = String(raw ?? '');
  const chars = [];
  const starts = [];
  const ends = [];
  let runStart = -1; // pending (not yet emitted) whitespace run in raw space
  let runEnd = -1;

  let i = 0;
  while (i < source.length) {
    const cp = source.codePointAt(i);
    let segEnd = i + (cp > 0xffff ? 2 : 1);
    while (segEnd < source.length) {
      const next = source.codePointAt(segEnd);
      if (!isCombiningMark(next)) break;
      segEnd += next > 0xffff ? 2 : 1;
    }

    const folded = source.slice(i, segEnd).normalize('NFKC').toLowerCase();
    for (const ch of folded) {
      if (FORMAT_CHAR_RE.test(ch)) continue;
      if (WHITESPACE_RE.test(ch)) {
        if (runStart === -1) runStart = i;
        runEnd = segEnd;
      } else {
        if (runStart !== -1 && chars.length > 0) {
          chars.push(' ');
          starts.push(runStart);
          ends.push(runEnd);
        }
        runStart = -1;
        chars.push(ch);
        starts.push(i);
        ends.push(segEnd);
      }
    }
    i = segEnd;
  }
  // A trailing whitespace run is never emitted (leading was skipped above).

  return { source, text: chars.join(''), starts, ends };
}

/** Normalize `raw` to its canonical match form (no offset map). */
export function normalizeText(raw) {
  return buildNormalizedView(raw).text;
}

/**
 * Recover the raw verbatim span behind normalized range [start, end).
 *
 * @param {{source: string, starts: number[], ends: number[]}} view
 * @returns {{start: number, end: number, verbatim: string}} raw offsets + slice
 */
export function rawSpanForMatch(view, start, end) {
  if (
    !Number.isInteger(start) || !Number.isInteger(end) ||
    start < 0 || end <= start || end > view.starts.length
  ) {
    throw new RangeError(`invalid normalized range [${start}, ${end}) for view of length ${view.starts.length}`);
  }
  const rawStart = view.starts[start];
  const rawEnd = view.ends[end - 1];
  return { start: rawStart, end: rawEnd, verbatim: view.source.slice(rawStart, rawEnd) };
}

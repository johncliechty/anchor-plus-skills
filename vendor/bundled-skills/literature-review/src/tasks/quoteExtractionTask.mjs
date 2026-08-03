// Wave 3 — the per-source verbatim-quote extraction task, run INSIDE an
// isolated worker (fork it via IsolatedWorker with this module as taskModule).
// Input:  { paperId, sourceText, candidates: [{ claimId, statement, quote, column? }] }
// Output: every candidate lands in `quotes` (grounded) or `rejected`
// (explicit reason — never silently dropped). Grounded records carry the
// verbatim raw span plus its start/end offsets into sourceText, so the
// Wave-4 terminal join can hyperlink and re-verify every claim
// deterministically. The whole result is structurally sanitized before it
// crosses the IPC boundary; the numeric offsets survive sanitization, which
// keeps the lineage verifiable: for any grounded record,
//   record.normalizedQuote === sanitizeText(normalizeText(sourceText.slice(start, end))).

import { buildNormalizedView } from '../textNormalization.mjs';
import { groundQuote } from '../quoteExtractor.mjs';
import { sanitizeStructure } from '../structuralSanitizer.mjs';

export default async function run(input, ctx) {
  const { paperId = 'unknown', sourceText = '', candidates = [] } = input ?? {};
  ctx.log(`verbatim-quote extraction started: ${paperId} (${candidates.length} candidate quotes)`);

  const view = buildNormalizedView(String(sourceText));
  const quotes = [];
  const rejected = [];

  for (let i = 0; i < candidates.length; i++) {
    const c = candidates[i] && typeof candidates[i] === 'object' ? candidates[i] : { quote: candidates[i] };
    const base = {
      claimId: String(c.claimId ?? `c-${i}`),
      statement: String(c.statement ?? ''),
      column: c.column === undefined || c.column === null ? null : String(c.column)
    };
    const match = groundQuote(view, String(c.quote ?? ''));
    if (match.matched) {
      quotes.push({
        ...base,
        verbatimQuote: match.verbatimQuote,
        normalizedQuote: match.normalizedQuote,
        start: match.start,
        end: match.end,
        occurrences: match.occurrences
      });
      ctx.progress(i + 1, candidates.length, `grounded ${base.claimId}`);
    } else {
      rejected.push({
        ...base,
        quote: String(c.quote ?? ''),
        reason: match.reason,
        rejection: `UNGROUNDED-QUOTE: quote failed strict matching against the normalized source (${match.reason})`
      });
      ctx.progress(i + 1, candidates.length, `rejected ${base.claimId} (${match.reason})`);
    }
  }

  return sanitizeStructure({
    paperId: String(paperId),
    stats: {
      candidates: candidates.length,
      grounded: quotes.length,
      rejected: rejected.length,
      sourceLength: String(sourceText).length,
      normalizedSourceLength: view.text.length
    },
    quotes,
    rejected
  });
}

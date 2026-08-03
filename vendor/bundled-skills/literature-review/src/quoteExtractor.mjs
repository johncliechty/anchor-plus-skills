// Wave 3 — verbatim quote extractor.
// Grounds candidate quotes against a source text by STRICT exact-string
// matching in the shared normal form (see textNormalization.mjs). A grounded
// quote comes back with the exact raw span it was extracted from, so the
// evidence lineage back to the primary source is byte-precise and any auditor
// (or the Wave-4 terminal join) can re-verify it deterministically. A quote
// that does not appear in the source is rejected EXPLICITLY with a reason —
// never silently kept, never silently dropped.

import { buildNormalizedView, normalizeText, rawSpanForMatch } from './textNormalization.mjs';

// A grounded quote shorter than this (normalized) is too weak to serve as
// evidence — matches the minimum the lean extraction path already enforces.
export const DEFAULT_MIN_QUOTE_LENGTH = 10;

function toView(sourceOrView) {
  return typeof sourceOrView === 'string' ? buildNormalizedView(sourceOrView) : sourceOrView;
}

/**
 * Ground one candidate quote against the source.
 *
 * @param {string|object} sourceOrView raw source text, or a prebuilt view from
 *   buildNormalizedView (build it once when grounding many quotes).
 * @param {string} candidateQuote
 * @param {{minLength?: number}} [options]
 * @returns {{matched: true, normalizedQuote: string, verbatimQuote: string,
 *            start: number, end: number, occurrences: number} |
 *           {matched: false, reason: string, normalizedQuote: string}}
 *   `start`/`end` are raw-source offsets; `verbatimQuote` is the exact raw
 *   slice; `occurrences` counts every normalized match in the source.
 */
export function groundQuote(sourceOrView, candidateQuote, { minLength = DEFAULT_MIN_QUOTE_LENGTH } = {}) {
  const view = toView(sourceOrView);
  const normalizedQuote = normalizeText(candidateQuote);
  if (normalizedQuote.length === 0) {
    return { matched: false, reason: 'empty-quote', normalizedQuote };
  }
  if (normalizedQuote.length < minLength) {
    return { matched: false, reason: 'too-short', normalizedQuote };
  }

  const first = view.text.indexOf(normalizedQuote);
  if (first === -1) {
    return { matched: false, reason: 'not-in-source', normalizedQuote };
  }
  let occurrences = 0;
  for (let idx = first; idx !== -1; idx = view.text.indexOf(normalizedQuote, idx + 1)) {
    occurrences += 1;
  }

  const span = rawSpanForMatch(view, first, first + normalizedQuote.length);
  return {
    matched: true,
    normalizedQuote,
    verbatimQuote: span.verbatim,
    start: span.start,
    end: span.end,
    occurrences
  };
}

/**
 * Ground a batch of candidate quotes against one source (the view is built
 * once). Every candidate lands in exactly one of `grounded` / `rejected` —
 * counts always add up to the input length.
 *
 * @param {string} rawSource
 * @param {Array<string|{claimId?: string, statement?: string, quote?: string}>} candidates
 * @param {{minLength?: number}} [options]
 * @returns {{grounded: object[], rejected: object[], normalizedSource: string}}
 */
export function extractVerbatimQuotes(rawSource, candidates, options = {}) {
  const view = buildNormalizedView(rawSource);
  const grounded = [];
  const rejected = [];

  (candidates ?? []).forEach((candidate, index) => {
    const c = candidate && typeof candidate === 'object' ? candidate : { quote: candidate };
    const claimId = String(c.claimId ?? `c-${index}`);
    const statement = String(c.statement ?? '');
    const match = groundQuote(view, String(c.quote ?? ''), options);
    if (match.matched) {
      grounded.push({ index, claimId, statement, ...match });
    } else {
      rejected.push({ index, claimId, statement, quote: String(c.quote ?? ''), ...match });
    }
  });

  return { grounded, rejected, normalizedSource: view.text };
}

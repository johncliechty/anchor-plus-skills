// src/text-sourcing.mjs — Wave 2 (2026-09-04, journal 0010): provenance-bearing text acquisition.
//
// The 0010 run left ten of twelve user seeds unextracted at ONE line: extraction read
// `cand.abstract || ''` and skipped "no text available" — while OpenAlex had every one
// of those abstracts (the snowball's OpenAlex mappers carry `abstract: null`; the
// inverted index is never decoded). This module is the fix: ONE bounded, auditable
// sourcing chain that seed and non-seed candidates alike take on the way to extraction,
//
//   provider abstract → OpenAlex abstract → Crossref abstract → arXiv/PMC full text → user PDF
//
// with the rules the plan names:
//
//   - INJECTED: every non-local link is an injected resolver function; a link with no
//     resolver injected for this run is stamped `skipped` (not applicable), never
//     silently absent. Hermetic tests inject stubs; the CLI injects real fetchers.
//   - BOUNDED: every resolver call races the per-link bound (DEFAULT_LINK_TIMEOUT_MS,
//     the plan's named numeric bound; override per run). A link that exceeds it is
//     REFUSED — stamped `timeout`, the chain moves on, the run is never blocked. An
//     invalid bound is refused outright (TypeError): an unnamed bound cannot be tested.
//   - AUDITABLE: every run of the chain returns one structured attempt per chain link,
//     in chain order — status `success` | `failed` | `timeout` | `error` | `skipped`
//     with a human-readable detail. `text_source` is the winning link's name, or
//     `none` only after every applicable link has failed.
//
// Everything here is deterministic given its injected sources: no ambient network, no
// clock in any stamp.

import { seedEntityIdToOpenAlexUrl, invertedIndexToAbstract } from './search.mjs';

// The decoder moved to search.mjs (2026-09-04) so the OpenAlex mappers decode at
// the first fetch; re-exported here so every existing import keeps working.
export { invertedIndexToAbstract };

export const TEXT_SOURCING_VERSION = 'litreview-text-sourcing/1';

/** The ordered chain — the exact link order the North Star names. */
export const SOURCING_CHAIN = Object.freeze([
  'provider-abstract',
  'openalex-abstract',
  'crossref-abstract',
  'arxiv-pmc-fulltext',
  'user-pdf',
]);

/** Stamped when every applicable link failed — never a winner's name. */
export const TEXT_SOURCE_NONE = 'none';

/** The per-link bound (ms) — the named numeric bound of the plan's boundedness gate. */
export const DEFAULT_LINK_TIMEOUT_MS = 10000;

/**
 * Race one resolver invocation against the per-link bound. A rejection that lands
 * AFTER the bound already won stays handled (no late unhandled-rejection): the refusal
 * was already stamped as `timeout`.
 *
 * @param {() => (string|null|Promise<string|null>)} run
 * @param {number} linkTimeoutMs
 * @returns {Promise<{ kind: 'resolved', value: unknown }|{ kind: 'timeout' }|{ kind: 'error', error: unknown }>}
 */
async function attemptWithinBound(run, linkTimeoutMs) {
  const timedOut = Symbol('link-timeout');
  let timer = null;
  const attempt = (async () => run())();
  attempt.catch(() => {}); // a post-timeout rejection is already stamped; never unhandled
  try {
    const raced = await Promise.race([
      attempt,
      new Promise((resolve) => { timer = setTimeout(resolve, linkTimeoutMs, timedOut); }),
    ]);
    if (raced === timedOut) return { kind: 'timeout' };
    return { kind: 'resolved', value: raced };
  } catch (err) {
    return { kind: 'error', error: err };
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

/**
 * Run the bounded sourcing chain for ONE candidate — seed or not, the same shape.
 *
 * The first link is local (the provider record's own abstract — always applicable,
 * `failed` when empty). Every later link runs ONLY if a resolver was injected under
 * its chain name (`skipped` otherwise) and ONLY while no earlier link has won
 * (`skipped — chain already satisfied` after a win, so the trail is always complete:
 * one attempt per chain link, in chain order).
 *
 * @param {object} candidate A canonical candidate record (candidate-assembly shape).
 * @param {object} [options]
 * @param {Record<string, (candidate: object) => (string|null|Promise<string|null>)>} [options.sources]
 *   Injected resolvers keyed by chain-link name; each returns the link's text or null.
 * @param {number} [options.linkTimeoutMs] Per-link bound in ms (positive integer).
 * @returns {Promise<{ text: string|null, text_source: string,
 *   attempts: Array<{ source: string, status: 'success'|'failed'|'timeout'|'error'|'skipped', detail: string }> }>}
 */
export async function acquireTextWithProvenance(candidate, { sources = {}, linkTimeoutMs = DEFAULT_LINK_TIMEOUT_MS } = {}) {
  if (candidate === null || typeof candidate !== 'object') {
    throw new TypeError('acquireTextWithProvenance: candidate must be an object');
  }
  if (sources === null || typeof sources !== 'object' || Array.isArray(sources)) {
    throw new TypeError('acquireTextWithProvenance: sources must be a map of chain-link name -> resolver');
  }
  if (!Number.isInteger(linkTimeoutMs) || linkTimeoutMs <= 0) {
    throw new TypeError(
      `acquireTextWithProvenance: linkTimeoutMs must be a positive integer (the per-link bound), got ${JSON.stringify(linkTimeoutMs)}`,
    );
  }

  const attempts = [];
  let winner = null;
  let text = null;

  // Link 1 — provider-abstract: the candidate record itself; local, always applicable.
  const providerAbstract = typeof candidate.abstract === 'string' ? candidate.abstract.trim() : '';
  if (providerAbstract !== '') {
    winner = SOURCING_CHAIN[0];
    text = candidate.abstract;
    attempts.push({ source: SOURCING_CHAIN[0], status: 'success', detail: `supplied ${providerAbstract.length} chars (provider record abstract)` });
  } else {
    attempts.push({ source: SOURCING_CHAIN[0], status: 'failed', detail: 'provider record carries no abstract text' });
  }

  for (const source of SOURCING_CHAIN.slice(1)) {
    if (winner !== null) {
      attempts.push({ source, status: 'skipped', detail: `not attempted — chain already satisfied by ${winner}` });
      continue;
    }
    const resolver = sources[source];
    if (typeof resolver !== 'function') {
      attempts.push({ source, status: 'skipped', detail: 'not applicable — no source injected for this run' });
      continue;
    }
    const raced = await attemptWithinBound(() => resolver(candidate), linkTimeoutMs);
    if (raced.kind === 'timeout') {
      attempts.push({ source, status: 'timeout', detail: `exceeded the ${linkTimeoutMs}ms per-link bound — attempt refused, chain continues` });
    } else if (raced.kind === 'error') {
      attempts.push({ source, status: 'error', detail: `source threw: ${raced.error?.message ?? String(raced.error)}` });
    } else {
      const value = typeof raced.value === 'string' ? raced.value : '';
      if (value.trim() !== '') {
        winner = source;
        text = value;
        attempts.push({ source, status: 'success', detail: `supplied ${value.length} chars of text` });
      } else {
        attempts.push({ source, status: 'failed', detail: 'source returned no text' });
      }
    }
  }

  return { text, text_source: winner ?? TEXT_SOURCE_NONE, attempts };
}

/**
 * Stamp one chain outcome onto a candidate record — the SAME provenance shape for
 * seeds and ordinary retained candidates: `text_source` (winning link or `none`) and
 * `text_source_attempts` (the complete ordered trail). Pure: returns a new record.
 *
 * @param {object} candidate
 * @param {{ text_source: string, attempts: Array<object> }} acquisition
 * @returns {object}
 */
export function stampTextProvenance(candidate, acquisition) {
  if (candidate === null || typeof candidate !== 'object') {
    throw new TypeError('stampTextProvenance: candidate must be an object');
  }
  if (
    acquisition === null || typeof acquisition !== 'object' ||
    typeof acquisition.text_source !== 'string' || !Array.isArray(acquisition.attempts)
  ) {
    throw new TypeError('stampTextProvenance: acquisition must carry text_source and attempts');
  }
  return {
    ...candidate,
    text_source: acquisition.text_source,
    text_source_attempts: acquisition.attempts.map((a) => ({ ...a })),
  };
}

// ── The OpenAlex-abstract resolver — the link 0010 needed. ──────────────────────────
//
// OpenAlex ships abstracts as an inverted index (word -> positions), which is why the
// snowball mappers carry `abstract: null` and ten seeds read "no text available" while
// the text existed. Decode it deterministically and resolve the work by CATALOG
// identity only (openalex: paperId; else the seed's doi/pmid/arxiv identity via the
// same DataCite-DOI convention search.mjs pins) — NEVER by fuzzy title.


const SEED_IDENTITY_TO_ENTITY_PREFIX = { doi: 'DOI:', pmid: 'PMID:', arxiv: 'arXiv:' };

/**
 * The OpenAlex work URL for a candidate's catalog identity, or null when the
 * candidate has none (no `openalex:` paperId, no doi/pmid/arxiv seed identity).
 *
 * @param {object} candidate
 * @returns {string|null}
 */
export function candidateOpenAlexUrl(candidate) {
  const paperId = String(candidate?.paperId ?? '');
  if (paperId.startsWith('openalex:')) {
    return `https://api.openalex.org/works/${paperId.slice('openalex:'.length)}`;
  }
  const identity = String(candidate?.seed_identity ?? '');
  const sep = identity.indexOf(':');
  if (sep > 0) {
    const prefix = SEED_IDENTITY_TO_ENTITY_PREFIX[identity.slice(0, sep)];
    if (prefix) return seedEntityIdToOpenAlexUrl(prefix + identity.slice(sep + 1));
  }
  // (2026-09-05, Grok review F1) any candidate with a catalog identity resolves: the
  // Semantic Scholar record's externalIds (DOI / ArXiv / PubMed) or a bare doi field —
  // an S2 SHA neighbour with a DOI is no longer a dead end for the chain.
  const ext = candidate?.externalIds && typeof candidate.externalIds === 'object' ? candidate.externalIds : null;
  const doi = (ext && typeof ext.DOI === 'string' && ext.DOI.trim())
    || (typeof candidate?.doi === 'string' && candidate.doi.trim()) || null;
  if (doi) return seedEntityIdToOpenAlexUrl('DOI:' + doi);
  if (ext && typeof ext.ArXiv === 'string' && ext.ArXiv.trim()) return seedEntityIdToOpenAlexUrl('arXiv:' + ext.ArXiv.trim());
  const pmid = ext && (typeof ext.PubMed === 'string' || typeof ext.PubMed === 'number') ? String(ext.PubMed).trim() : '';
  if (pmid) return seedEntityIdToOpenAlexUrl('PMID:' + pmid);
  return null;
}

/**
 * Source text for the candidates that carry NO abstract, BEFORE relevance ranking —
 * the Grok review of the build (2026-09-05, finding 1): on the live path Semantic
 * Scholar returns many records without abstracts, so ranking on the provider text
 * alone scored them on their titles and excluded on-topic neighbours as off-topic.
 * Pure over the injected sources: a candidate that gains text carries it as `abstract`
 * and keeps the winning link as `text_source`; one that gains none is stamped `none`
 * (and the extraction stage will try again, honestly). Candidates that already have
 * text are untouched.
 *
 * @param {object[]} candidates canonical candidate records
 * @param {object} [options] `sources`, `linkTimeoutMs` as for acquireTextWithProvenance
 * @returns {Promise<{ candidates: object[], attempted: number, sourced: number }>}
 */
export async function preScreenSourcing(candidates, { sources = {}, linkTimeoutMs = DEFAULT_LINK_TIMEOUT_MS } = {}) {
  if (!Array.isArray(candidates)) throw new TypeError('preScreenSourcing: candidates must be an array');
  const out = [];
  let attempted = 0;
  let sourced = 0;
  for (const c of candidates) {
    const hasText = typeof c?.abstract === 'string' && c.abstract.trim() !== '';
    if (hasText || candidateOpenAlexUrl(c) === null && !Object.keys(sources).some((k) => k !== 'openalex-abstract')) {
      out.push(c);
      continue;
    }
    attempted += 1;
    const acquisition = await acquireTextWithProvenance(c, { sources, linkTimeoutMs });
    const stamped = stampTextProvenance(c, acquisition);
    if (typeof acquisition.text === 'string' && acquisition.text.trim() !== '') {
      sourced += 1;
      out.push({ ...stamped, abstract: acquisition.text });
    } else {
      out.push(stamped);
    }
  }
  return { candidates: out, attempted, sourced };
}

/**
 * Build the `openalex-abstract` chain resolver over an injected fetch (hermetic in
 * tests; the CLI passes the real one). Returns the decoded abstract, or null when the
 * candidate has no catalog identity, the work is not found, or it carries no index —
 * the chain stamps those as `failed`, honestly.
 *
 * @param {{ fetch?: typeof globalThis.fetch }} [options]
 * @returns {(candidate: object) => Promise<string|null>}
 */
export function makeOpenAlexAbstractResolver({
  fetch = globalThis.fetch, maxRetries = 2, mailto = process.env.OPENALEX_MAILTO || null,
} = {}) {
  if (typeof fetch !== 'function') {
    throw new TypeError('makeOpenAlexAbstractResolver: a fetch function is required');
  }
  return async function openAlexAbstractResolver(candidate) {
    const base = candidateOpenAlexUrl(candidate);
    if (base === null) return null;
    // (2026-09-05, Grok review F5) the same backoff fetch the snowball uses — a 429 during
    // sourcing is retried, not stamped `failed` and skipped; a polite mailto when set.
    const url = mailto ? `${base}${base.includes('?') ? '&' : '?'}mailto=${encodeURIComponent(mailto)}` : base;
    const res = await fetchRetryingLimits(fetch, url, { maxRetries });
    if (!res || res.ok !== true) return null;
    const work = await res.json();
    return invertedIndexToAbstract(work?.abstract_inverted_index);
  };
}

/**
 * Fetch with retries ONLY for rate limits, server errors and thrown network errors
 * (429 / 5xx / throw) — a 404 is an answer ("no such work"), never retried. Honors
 * Retry-After; bounded jittered backoff. Returns the last response, or null after a
 * final throw.
 */
export async function fetchRetryingLimits(fetch, url, { maxRetries = 2, baseDelayMs = 250, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let attempt = 0;
  for (;;) {
    let res = null;
    let threw = false;
    try {
      res = await fetch(url);
    } catch {
      threw = true;
    }
    const retryable = threw || (res && res.ok !== true && (res.status === 429 || (typeof res.status === 'number' && res.status >= 500)));
    if (!retryable || attempt >= maxRetries) return threw ? null : res;
    let waitMs = Math.min(4000, Math.random() * baseDelayMs * Math.pow(2, attempt + 1));
    const ra = res?.headers?.get?.('retry-after');
    if (ra != null && ra !== '' && Number.isFinite(Number(ra))) waitMs = Math.max(waitMs, Number(ra) * 1000);
    await sleep(waitMs);
    attempt += 1;
  }
}

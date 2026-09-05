import fs from 'node:fs/promises';
import { validateSchema } from './validateSchema.mjs';

/**
 * Decode an OpenAlex `abstract_inverted_index` into plain text. Lives here (not in
 * text-sourcing.mjs, which imports this module) so the OpenAlex mappers below can
 * carry the abstract from the first fetch — the Gandalf read of the 0010 build
 * (2026-09-04) found every OpenAlex neighbour reached relevance screening with
 * `abstract: null`, so TF-IDF ranked it on its title alone and could exclude an
 * on-topic paper as off-topic before the sourcing chain ever ran.
 *
 * @param {Record<string, number[]>|null|undefined} index
 * @returns {string|null} the abstract, or null when the index is absent/empty
 */
export function invertedIndexToAbstract(index) {
  if (index === null || typeof index !== 'object' || Array.isArray(index)) return null;
  const slots = [];
  for (const [word, positions] of Object.entries(index)) {
    if (!Array.isArray(positions)) continue;
    for (const pos of positions) {
      if (Number.isInteger(pos) && pos >= 0) slots[pos] = word;
    }
  }
  const words = slots.filter((w) => typeof w === 'string');
  return words.length > 0 ? words.join(' ') : null;
}

// C8 (2026-07-11): the whitelist is a RANKING prior, not an exclusion list, by default.
// The old default EXCLUDED everything outside 3 ML/security venues — arXiv preprints
// (empty venue) all died as 'low-venue', so a real snowball yielded near-zero candidates
// — and a test fixture ('Some Local Workshop') had leaked into production. Venue
// EXCLUSION is now opt-in via options.excludeByVenue.
export const DEFAULT_VENUE_WHITELIST = {
  venues: [
    { name: 'Conference on Neural Information Processing Systems', abbr: 'NeurIPS', tier: 'Tier-1' },
    { name: 'International Conference on Machine Learning', abbr: 'ICML', tier: 'Tier-1' },
    { name: 'Nature', abbr: 'Nature', tier: 'Tier-1' },
    { name: 'Science', abbr: 'Science', tier: 'Tier-1' },
    { name: 'ACM Conference on Computer and Communications Security', abbr: 'CCS', tier: 'Tier-2' }
  ]
};

/**
 * Matches a venue string case-insensitively and trimmed against the whitelist names and abbreviations.
 * Falls back to case-insensitive substring matching if exact matches are not found.
 */
export function matchVenue(venueStr, whitelist) {
  if (!venueStr) return null;
  const cleaned = venueStr.toLowerCase().trim();

  // 1. Exact match
  for (const v of whitelist.venues || []) {
    const name = (v.name || '').toLowerCase().trim();
    const abbr = (v.abbr || '').toLowerCase().trim();
    if (cleaned === name || cleaned === abbr) {
      return v;
    }
  }

  // 2. Substring match
  for (const v of whitelist.venues || []) {
    const name = (v.name || '').toLowerCase().trim();
    const abbr = (v.abbr || '').toLowerCase().trim();
    if (name && (cleaned.includes(name) || name.includes(cleaned))) {
      return v;
    }
    if (abbr && (cleaned.includes(abbr) || abbr.includes(cleaned))) {
      return v;
    }
  }

  return null;
}

/**
 * Sorts/ranks candidates deterministically:
 * Whitelist Tier (Tier-1 > Tier-2 > Tier-3) -> citation count (desc) -> publication year (desc) -> paperId (alphabetical).
 */
export function rankCandidates(candidates, whitelist) {
  return [...candidates].sort((a, b) => {
    const vA = matchVenue(a.venue, whitelist);
    const vB = matchVenue(b.venue, whitelist);

    const tierMap = { 'Tier-1': 1, 'Tier-2': 2, 'Tier-3': 3 };
    const tierA = vA ? (tierMap[vA.tier] || 4) : 4;
    const tierB = vB ? (tierMap[vB.tier] || 4) : 4;

    if (tierA !== tierB) {
      return tierA - tierB;
    }

    const citA = a.citationCount || 0;
    const citB = b.citationCount || 0;
    if (citA !== citB) {
      return citB - citA;
    }

    const yA = a.year || 0;
    const yB = b.year || 0;
    if (yA !== yB) {
      return yB - yA;
    }

    return (a.paperId || '').localeCompare(b.paperId || '');
  });
}

/**
 * Retries a request with exponential backoff on rate limits (429) or server errors (>= 500).
 *
 * P1 2026-07-25 (journal 0001 — the skill's ONLY real run failed on a hard S2 429):
 * the old defaults (maxRetries 3, backoffFactor 50ms → ~0.7s TOTAL budget) were a
 * unit-test constant shipped as production; against Semantic Scholar's shared
 * unauthenticated pool (minute-scale windows) they exhausted in under a second.
 * Now: `Retry-After` is honored when the server sends it; the default base is 1s
 * with full jitter and a 60s per-wait cap; and `S2_API_KEY` (env) is sent as
 * `x-api-key` so a keyed operator gets the authenticated pool. Injectable
 * `sleep`/`fetch` keep tests fast (tests pass a tiny backoffFactor explicitly).
 */
export const DEFAULT_BACKOFF_MS = 1000;
export const MAX_BACKOFF_WAIT_MS = 60_000;

export function s2Headers(env = process.env) {
  const key = env && typeof env.S2_API_KEY === 'string' ? env.S2_API_KEY.trim() : '';
  return key ? { 'x-api-key': key } : {};
}

async function fetchWithBackoff(url, options = {}) {
  const customFetch = options.fetch || fetch;
  const fetchOptions = { ...(options.fetchOptions || {}) };
  fetchOptions.headers = { ...s2Headers(options.env), ...(fetchOptions.headers || {}) };
  const maxRetries = options.maxRetries ?? 3;
  const backoffFactor = options.backoffFactor ?? DEFAULT_BACKOFF_MS; // ms
  const sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));

  let attempt = 0;
  while (true) {
    let retryAfterMs = null;
    try {
      const response = await customFetch(url, fetchOptions);
      if (response.ok) {
        return response;
      }

      if (response.status === 429 || response.status >= 500) {
        if (attempt >= maxRetries) {
          throw new Error(`HTTP error ${response.status} ${response.statusText} after ${maxRetries} retries`);
        }
        // Honor the server's own instruction when present (seconds or HTTP-date).
        const ra = response.headers?.get?.('retry-after');
        if (ra != null && ra !== '') {
          const secs = Number(ra);
          if (Number.isFinite(secs) && secs >= 0) retryAfterMs = secs * 1000;
          else {
            const when = Date.parse(ra);
            if (Number.isFinite(when)) retryAfterMs = Math.max(0, when - Date.now());
          }
        }
      } else {
        throw new Error(`HTTP error ${response.status} ${response.statusText}`);
      }
    } catch (error) {
      if (attempt >= maxRetries) {
        throw error;
      }
    }

    attempt++;
    // Full jitter over the exponential step; Retry-After (when sent) is the floor.
    const step = backoffFactor * Math.pow(2, attempt);
    const jittered = Math.random() * step;
    const delay = Math.min(Math.max(retryAfterMs ?? 0, jittered), MAX_BACKOFF_WAIT_MS);
    await sleep(delay);
  }
}

export { fetchWithBackoff };

/**
 * Evaluates a candidate paper against filters, returning { excluded: boolean, reason: string, details: string }.
 */
export function evaluateFilters(paper, whitelist, options = {}) {
  // 1. Date range filter
  if (options.minYear !== undefined && paper.year !== undefined && paper.year !== null) {
    if (paper.year < options.minYear) {
      return {
        excluded: true,
        reason: 'date-range',
        details: `Published in ${paper.year}, but minYear is ${options.minYear}`
      };
    }
  }

  // 2. PDF availability filter
  if (options.requirePdf) {
    const hasPdf = paper.openAccessPdf || paper.pdfUrl || paper.hasPdf;
    if (!hasPdf) {
      return {
        excluded: true,
        reason: 'no-pdf',
        details: 'No open access PDF link available'
      };
    }
  }

  // 3. Venue whitelist filter — OPT-IN (C8): by default the whitelist only RANKS;
  // it excludes only when the operator explicitly asks (options.excludeByVenue).
  if (whitelist && options.excludeByVenue) {
    const matched = matchVenue(paper.venue, whitelist);
    if (!matched) {
      return {
        excluded: true,
        reason: 'low-venue',
        details: `Venue "${paper.venue || 'Unknown'}" is not in the whitelist`
      };
    }

    // 4. Venue tier filter
    if (options.minTier) {
      const tierMap = { 'Tier-1': 1, 'Tier-2': 2, 'Tier-3': 3 };
      const paperTierValue = tierMap[matched.tier] || 4;
      const minTierValue = tierMap[options.minTier] || 4;
      if (paperTierValue > minTierValue) {
        return {
          excluded: true,
          reason: 'low-tier',
          details: `Venue "${paper.venue}" tier is ${matched.tier}, but minTier is ${options.minTier}`
        };
      }
    }
  }

  return { excluded: false };
}

/**
 * Formats a visual citation graph as a Mermaid markdown diagram.
 */
export function generateMermaidGraph(nodes, edges) {
  let mermaid = 'graph TD\n';
  for (const node of nodes) {
    const cleanTitle = (node.title || 'Untitled')
      .replace(/"/g, '\\"')
      .replace(/[\n\r]/g, ' ')
      .slice(0, 50);
    const venue = node.venue || 'No Venue';
    const year = node.year || 'No Year';
    mermaid += `  ${node.paperId}["${cleanTitle}\\n(${venue}, ${year})"]\n`;
    if (node.status === 'excluded') {
      mermaid += `  style ${node.paperId} fill:#ffcccc,stroke:#333,stroke-width:1px\n`;
    } else {
      mermaid += `  style ${node.paperId} fill:#ccffcc,stroke:#333,stroke-width:2px\n`;
    }
  }
  for (const edge of edges) {
    mermaid += `  ${edge.source} --> ${edge.target}\n`;
  }
  return mermaid;
}

// ── OpenAlex fallback provider (P2 2026-07-25 — the North-Star breadth ask AND the
// cure for single-provider total outage: journal 0001's only real run died with S2).
// When an S2 reference expansion fails AFTER real retries, the walk falls back to
// OpenAlex BY TITLE: /works?search=<title> → referenced_works → one batched hydrate.
// Fallback papers carry `openalex:`-prefixed ids and re-expand via OpenAlex; every
// fallback is RECORDED (provider stamped) — a provider switch is never silent.

export async function fetchReferencesOpenAlex(title, options = {}) {
  const base = 'https://api.openalex.org';
  const enc = encodeURIComponent(String(title).slice(0, 300));
  const sRes = await fetchWithBackoff(`${base}/works?search=${enc}&per-page=1`, options);
  const sData = await sRes.json();
  const work = sData?.results?.[0];
  if (!work || !Array.isArray(work.referenced_works) || !work.referenced_works.length) return [];
  const ids = work.referenced_works.slice(0, 50).map((u) => String(u).split('/').pop());
  const fRes = await fetchWithBackoff(
    `${base}/works?filter=openalex_id:${ids.join('|')}&per-page=${ids.length}`, options);
  const fData = await fRes.json();
  return (fData?.results ?? []).map((w) => ({
    paperId: `openalex:${String(w.id).split('/').pop()}`,
    title: w.title ?? w.display_name ?? 'Untitled',
    venue: w.primary_location?.source?.display_name ?? w.host_venue?.display_name ?? 'Unknown',
    year: w.publication_year ?? null,
    citationCount: w.cited_by_count ?? 0,
    authors: (w.authorships ?? []).map((a) => ({ name: a.author?.display_name ?? '?' })),
    openAccessPdf: w.open_access?.oa_url ? { url: w.open_access.oa_url } : null,
    abstract: invertedIndexToAbstract(w.abstract_inverted_index),
    provider: 'openalex',
  }));
}

/** Expand one OpenAlex-id paper's references (the openalex: re-expansion route). */
export async function expandOpenAlexId(openAlexId, options = {}) {
  const base = 'https://api.openalex.org';
  const id = String(openAlexId).replace(/^openalex:/, '');
  const res = await fetchWithBackoff(`${base}/works/${id}`, options);
  const w = await res.json();
  if (!Array.isArray(w?.referenced_works) || !w.referenced_works.length) return [];
  const ids = w.referenced_works.slice(0, 50).map((u) => String(u).split('/').pop());
  const fRes = await fetchWithBackoff(
    `${base}/works?filter=openalex_id:${ids.join('|')}&per-page=${ids.length}`, options);
  const fData = await fRes.json();
  return (fData?.results ?? []).map((x) => ({
    paperId: `openalex:${String(x.id).split('/').pop()}`,
    title: x.title ?? x.display_name ?? 'Untitled',
    venue: x.primary_location?.source?.display_name ?? 'Unknown',
    year: x.publication_year ?? null,
    citationCount: x.cited_by_count ?? 0,
    authors: (x.authorships ?? []).map((a) => ({ name: a.author?.display_name ?? '?' })),
    openAccessPdf: x.open_access?.oa_url ? { url: x.open_access.oa_url } : null,
    abstract: invertedIndexToAbstract(x.abstract_inverted_index),
    provider: 'openalex',
  }));
}

/** Map one OpenAlex work object to the pipeline's paper shape (same shape the
 *  reference-expansion fallbacks above emit). */
function openAlexWorkToPaper(w) {
  return {
    paperId: `openalex:${String(w.id).split('/').pop()}`,
    title: w.title ?? w.display_name ?? 'Untitled',
    venue: w.primary_location?.source?.display_name ?? w.host_venue?.display_name ?? 'Unknown',
    year: w.publication_year ?? null,
    citationCount: w.cited_by_count ?? 0,
    authors: (w.authorships ?? []).map((a) => ({ name: a.author?.display_name ?? '?' })),
    openAccessPdf: w.open_access?.oa_url ? { url: w.open_access.oa_url } : null,
    abstract: invertedIndexToAbstract(w.abstract_inverted_index),
    provider: 'openalex',
  };
}

// ── Seed-LOAD fallback (2026-08-25 — the journal-0004 fix, John-ratified elegance card).
// The single call gating the ENTIRE live pipeline was the S2 seed-paper load: 8 of 9
// real invocations died there on sustained 429 (journal 0004, 2026-07-29). Same law as
// the expansion fallback above: after real S2 retries fail, fall back to OpenAlex BY
// CATALOG IDENTIFIER (doi/pmid directly; arXiv via its DataCite DOI) — NEVER by fuzzy
// title (seed-identity.mjs pins that refusal). Every fallback is RECORDED, never silent.
export function seedEntityIdToOpenAlexUrl(seedEntityId) {
  const s = String(seedEntityId);
  if (/^DOI:/i.test(s)) return `https://api.openalex.org/works/doi:${s.slice(4)}`;
  if (/^PMID:/i.test(s)) return `https://api.openalex.org/works/pmid:${s.slice(5)}`;
  if (/^arXiv:/i.test(s)) return `https://api.openalex.org/works/doi:10.48550/arXiv.${s.slice(6)}`;
  return null;
}

export async function resolveSeedPaperWithFallback(seedEntityId, options = {}) {
  const customFetch = options.fetch || fetch;
  let s2Err;
  try {
    const seedUrl = `https://api.semanticscholar.org/graph/v1/paper/${seedEntityId}?fields=title,venue,year,citationCount,authors,openAccessPdf,abstract,externalIds`;
    const res = await fetchWithBackoff(seedUrl, { ...options, fetch: customFetch });
    const data = await res.json();
    if (data && data.paperId) return { paper: data, provider: 's2' };
    s2Err = new Error('S2 returned no paperId for the seed');
  } catch (err) {
    s2Err = err;
  }
  const oaUrl = seedEntityIdToOpenAlexUrl(seedEntityId);
  if (!oaUrl) {
    throw new Error(`Failed to fetch seed paper metadata: ${s2Err.message} (no OpenAlex identifier route for ${seedEntityId})`);
  }
  try {
    const res = await fetchWithBackoff(oaUrl, { ...options, fetch: customFetch });
    const w = await res.json();
    if (!w || !w.id) throw new Error('OpenAlex returned no work for the identifier');
    return { paper: openAlexWorkToPaper(w), provider: 'openalex', fallbackReason: `s2: ${s2Err.message}` };
  } catch (oaErr) {
    throw new Error(`Failed to fetch seed paper metadata from BOTH providers — s2: ${s2Err.message}; openalex: ${oaErr.message}`);
  }
}

/**
 * Performs a depth-bounded citation snowball search starting from seedEntityId.
 */
export async function performSnowballSearch(seedEntityId, venueWhitelist, options = {}) {
  const depthLimit = options.depth ?? 1;
  const customFetch = options.fetch || fetch;
  
  const allPapers = new Map();
  const edges = [];
  const visited = new Set();
  const queue = [];
  const fetchFailures = []; // P1 2026-07-25: honest record of truncated expansions
  const providerFallbacks = []; // P2 2026-07-25: OpenAlex fallbacks, stamped never silent

  // Seed entry. P2 2026-07-25: when the caller already HOLDS the seed metadata
  // (ingest resolved it), `options.seedPaper` skips one fragile network call — and
  // gives the OpenAlex by-title fallback a title to work with from round one.
  if (options.seedPaper && options.seedPaper.paperId) {
    allPapers.set(options.seedPaper.paperId, options.seedPaper);
    queue.push({ paperId: options.seedPaper.paperId, depth: 0 });
    visited.add(options.seedPaper.paperId);
    // A pre-flight-resolved seed that came via a provider fallback is RECORDED here
    // (2026-08-25 review fix — the fallback previously bypassed providerFallbacks
    // entirely on the now-primary pre-flight path).
    if (options.seedPaperFallback) {
      providerFallbacks.push({ stage: 'seed-load(pre-flight)', entityId: String(seedEntityId), ...options.seedPaperFallback });
    }
  } else {
    // Fetch seed paper details first — with the RECORDED OpenAlex fallback (the
    // journal-0004 fix): the run now dies here only when BOTH providers fail.
    const resolved = await resolveSeedPaperWithFallback(seedEntityId, { fetch: customFetch, ...options });
    if (resolved.provider !== 's2') {
      providerFallbacks.push({ stage: 'seed-load', entityId: String(seedEntityId), from: 's2', to: resolved.provider, reason: resolved.fallbackReason });
    }
    allPapers.set(resolved.paper.paperId, resolved.paper);
    queue.push({ paperId: resolved.paper.paperId, depth: 0 });
    visited.add(resolved.paper.paperId);
  }

  // Traversal loop (BFS)
  while (queue.length > 0) {
    const { paperId, depth } = queue.shift();
    const currentPaper = allPapers.get(paperId);

    // If we've reached the depth limit, we do not query references of this paper.
    if (depth >= depthLimit) {
      continue;
    }

    // Fetch references of current paper. `openalex:` ids re-expand via OpenAlex;
    // an S2 failure falls back to OpenAlex-by-title before being recorded as a loss.
    try {
      let refs;
      if (String(paperId).startsWith('openalex:')) {
        refs = await expandOpenAlexId(paperId, { fetch: customFetch, ...options });
      } else {
        try {
          const refUrl = `https://api.semanticscholar.org/graph/v1/paper/${paperId}/references?fields=title,venue,year,citationCount,authors,openAccessPdf,abstract,externalIds`;
          const res = await fetchWithBackoff(refUrl, { fetch: customFetch, ...options });
          const responseData = await res.json();
          refs = responseData.data || responseData.references || [];
        } catch (s2err) {
          const title = allPapers.get(paperId)?.title;
          if (!title) throw s2err;
          refs = await fetchReferencesOpenAlex(title, { fetch: customFetch, ...options });
          providerFallbacks.push({ paperId, title, provider: 'openalex', s2_error: String(s2err?.message || s2err).slice(0, 200) });
        }
      }
      for (const item of refs) {
        const refPaper = item.citedPaper || item;
        if (!refPaper || !refPaper.paperId) continue;

        const childId = refPaper.paperId;
        
        // Record the edge
        edges.push({ source: paperId, target: childId });

        if (!visited.has(childId)) {
          visited.add(childId);
          allPapers.set(childId, refPaper);

          // Evaluate filters for the paper
          const filterResult = evaluateFilters(refPaper, venueWhitelist, options);
          refPaper.filterResult = filterResult;

          // If not excluded, and depth is within limits, queue it
          if (!filterResult.excluded) {
            if (depth + 1 < depthLimit) {
              queue.push({ paperId: childId, depth: depth + 1 });
            }
          }
        }
      }
    } catch (err) {
      // P1 2026-07-25 (journal 0001): a mid-walk fetch failure used to be SWALLOWED
      // SILENTLY — a rate-limited run quietly truncated the citation graph with no
      // stamp anywhere ("each stage honest about what ran" was false for the evidence
      // base itself). The walk still proceeds with what it has, but the loss is now
      // RECORDED: a PRISMA `fetch-failed` exclusion entry per failed expansion.
      fetchFailures.push({
        paperId,
        title: (allPapers.get(paperId)?.title) || 'Untitled',
        error: String(err?.message || err).slice(0, 300),
      });
    }
  }

  // Prepare final results
  const nodes = [];
  const exclusions = [];
  const candidates = [];

  for (const f of fetchFailures) {
    exclusions.push({
      paperId: f.paperId,
      title: f.title,
      reason: 'fetch-failed',
      details: `reference expansion failed (${f.error}) — this paper's outgoing citations are MISSING from the graph (evidence base truncated here)`,
    });
  }

  for (const [id, paper] of allPapers.entries()) {
    const isSeed = id === seedEntityId;
    
    // Evaluate filters for seed too, or keep it included. Let's evaluate it for nodes representation.
    const filterResult = isSeed ? { excluded: false } : (paper.filterResult || evaluateFilters(paper, venueWhitelist, options));
    
    const nodeStatus = filterResult.excluded ? 'excluded' : 'included';
    nodes.push({
      paperId: id,
      title: paper.title || 'Untitled',
      venue: paper.venue || 'Unknown',
      year: paper.year || null,
      status: nodeStatus,
      reason: filterResult.reason || null
    });

    if (filterResult.excluded) {
      exclusions.push({
        paperId: id,
        title: paper.title || 'Untitled',
        reason: filterResult.reason,
        details: filterResult.details || ''
      });
    } else {
      candidates.push(paper);
    }
  }

  // Deterministically rank the candidates
  const rankedCandidates = rankCandidates(candidates, venueWhitelist);

  // Schema-validate the exclusions
  const prismaExclusions = { exclusions };
  validateSchema(prismaExclusions, 'PrismaExclusions');

  // Write exclusions file if path provided
  if (options.exclusionsPath) {
    await fs.writeFile(options.exclusionsPath, JSON.stringify(prismaExclusions, null, 2), 'utf8');
  }

  // Generate Mermaid graph
  const mermaid = generateMermaidGraph(nodes, edges);

  return {
    graph: { nodes, edges },
    prismaExclusions,
    candidates: rankedCandidates,
    mermaid,
    // P1 2026-07-25: non-empty ⇒ the evidence base is TRUNCATED (stamped, never silent).
    fetchFailures,
    // P2 2026-07-25: non-empty ⇒ parts of the walk came via OpenAlex (stamped provider switch).
    providerFallbacks,
  };
}

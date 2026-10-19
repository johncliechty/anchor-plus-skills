// src/seed-identity.mjs — Wave 10: lit-review-side deterministic seed identity and
// cross-seed dedupe over the SHARED pinned precedence DOI -> PMID -> arXiv-id ->
// normalized-title-hash (trio-shared/brownfield-intake/seedIdentity.mjs owns the
// precedence, the strict formats, and the pinned title-normalization spec — this
// module adds NO second identity convention).
//
// Dedupe REFUSES to fuzzy-merge, at both layers:
//
//   LIST layer (dedupeSeedList): only EXACT identity-key duplicates collapse
//   (doi:10.1000/x supplied twice is one seed). Seeds with different identity keys
//   are NEVER merged here — not even on identical titles — because same-paper-ness
//   across identifier types is only provable at snowball time, when both identifiers
//   resolve to the same catalog paperId. Id-less (title-hash) seeds whose normalized
//   titles are similar but NOT equal are kept DISTINCT and FLAGGED for the user.
//
//   SNOWBALL layer (mergeSnowballResults): per-seed snowball results merge by EXACT
//   paperId equality — the catalog's own identity, zero string similarity. When two
//   seeds resolve to the same paperId, the merged seed paper is attributed to the
//   highest-precedence seed identity (DOI -> PMID -> arXiv-id -> title-hash) and the
//   merge is recorded, so repeated runs produce an identical dedupe result.
//
// A title-hash seed has NO external catalog identity; seedEntityId() returns null for
// it and snowball skips it honestly — resolving it by fuzzy title search is exactly
// the merge this module refuses to do.

import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { resolveResearchPrimeRoot } from './stage0-plan.mjs';
import { rankCandidates, generateMermaidGraph } from './search.mjs';
import { validateSchema } from './validateSchema.mjs';

export const SEED_IDENTITY_VERSION = 'litreview-seed-identity/1';

/**
 * The pinned identity precedence, highest first — MIRRORS the shared module's
 * SEED_ID_PRECEDENCE (test/seed-dedupe-determinism.test.mjs pins the two equal, so
 * they can never silently diverge). Inlined so mergeSnowballResults stays synchronous.
 * @type {ReadonlyArray<string>}
 */
export const LITREVIEW_SEED_ID_PRECEDENCE = Object.freeze(['doi', 'pmid', 'arxiv', 'title-hash']);

/** Catalog (Semantic Scholar) entity-id prefixes per external identifier type. */
export const SEED_ENTITY_ID_PREFIXES = Object.freeze({
  doi: 'DOI:',
  pmid: 'PMID:',
  arxiv: 'arXiv:',
});

/** Advisory collision-flag threshold: token-set Jaccard at or above this flags a
 *  similar-title pair of id-less seeds. Flagging is display-only — NEVER a merge. */
export const TITLE_COLLISION_MIN_JACCARD = 0.5;

let sharedSeedIdentityCache = null;

/**
 * Load the SHARED seed-identity module from the pinned trio home (resolved through
 * researchPrime's own contract.mjs TRIO_ROOT pin — the Wave-1 decision-receipt rules,
 * same as src/stage0-plan.mjs). Cached after the first call.
 *
 * @returns {Promise<typeof import('C:/dev/trio/trio-shared/brownfield-intake/seedIdentity.mjs')>}
 */
export async function loadSharedSeedIdentity() {
  if (!sharedSeedIdentityCache) {
    const contract = await import(
      pathToFileURL(path.join(resolveResearchPrimeRoot(), 'bin', 'contract.mjs')).href
    );
    sharedSeedIdentityCache = await import(
      new URL('trio-shared/brownfield-intake/seedIdentity.mjs', contract.TRIO_ROOT).href
    );
  }
  return sharedSeedIdentityCache;
}

/**
 * Map a validated seed to its external catalog entity id, or null when the seed has
 * no external identity (title-hash). Null is honest: a title-hash seed is kept in the
 * plan but skipped by snowball — never resolved by fuzzy title search.
 *
 * @param {{ idType: string, id: string }} seed A validated seed.
 * @returns {string|null} e.g. 'DOI:10.1000/x', 'PMID:123', 'arXiv:2203.15556', or null
 */
export function seedEntityId(seed) {
  if (typeof seed !== 'object' || seed === null || typeof seed.idType !== 'string' || typeof seed.id !== 'string') {
    throw new TypeError('seedEntityId: seed must be a validated { idType, id } object');
  }
  const prefix = SEED_ENTITY_ID_PREFIXES[seed.idType];
  return prefix === undefined ? null : `${prefix}${seed.id}`;
}

/** Deterministic precedence comparator (lower = higher precedence; ties by id). */
function compareByPrecedence(a, b) {
  const pa = LITREVIEW_SEED_ID_PRECEDENCE.indexOf(a.idType);
  const pb = LITREVIEW_SEED_ID_PRECEDENCE.indexOf(b.idType);
  if (pa !== pb) return pa - pb;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Token set of a pinned-normalized title (the normalization is the shared spec). */
function titleTokenSet(normalizedTitle) {
  return new Set(normalizedTitle.split(' ').filter(Boolean));
}

/** Token-set Jaccard similarity — advisory flagging input only, never a merge key. */
function jaccard(aSet, bSet) {
  if (aSet.size === 0 && bSet.size === 0) return 0;
  let inter = 0;
  for (const t of aSet) if (bSet.has(t)) inter += 1;
  return inter / (aSet.size + bSet.size - inter);
}

/**
 * Deterministic LIST-layer dedupe of a validated seed list:
 *
 *   - EXACT identity-key duplicates (same `idType:id`) collapse to the first
 *     occurrence; every collapse is recorded in `merges`.
 *   - Nothing else merges. Seeds with different identity keys stay distinct even on
 *     identical titles (same-paper-ness is proven at snowball time by paperId).
 *   - Id-less (title-hash) seed PAIRS whose normalized titles are similar but not
 *     equal (containment, or token Jaccard >= TITLE_COLLISION_MIN_JACCARD) are kept
 *     DISTINCT and flagged in `collisions` for the user. No fuzzy merge, ever.
 *
 * Output order is first-occurrence input order — deterministic for a given input.
 *
 * @param {ReadonlyArray<{ idType: string, id: string, title: string }>} seeds
 *   Strictly-validated seeds (the seed-adapter's canonical list).
 * @returns {Promise<{
 *   seeds: ReadonlyArray<object>,
 *   merges: Array<{ key: string, kept: object, absorbedCount: number }>,
 *   collisions: Array<{ left: string, right: string, leftTitle: string,
 *     rightTitle: string, reason: string }>,
 * }>}
 */
export async function dedupeSeedList(seeds) {
  if (!Array.isArray(seeds)) {
    throw new TypeError('dedupeSeedList: seeds must be an array of validated seeds');
  }
  const si = await loadSharedSeedIdentity();

  const kept = [];
  const mergesByKey = new Map();
  const seen = new Map();
  for (const seed of seeds) {
    const key = si.seedIdentityKey(seed);
    if (seen.has(key)) {
      if (!mergesByKey.has(key)) {
        mergesByKey.set(key, { key, kept: seen.get(key), absorbedCount: 0 });
      }
      mergesByKey.get(key).absorbedCount += 1;
      continue;
    }
    seen.set(key, seed);
    kept.push(seed);
  }

  const collisions = [];
  const idless = kept.filter((s) => s.idType === 'title-hash');
  for (let i = 0; i < idless.length; i += 1) {
    for (let j = i + 1; j < idless.length; j += 1) {
      const normA = si.normalizeTitleForHash(idless[i].title);
      const normB = si.normalizeTitleForHash(idless[j].title);
      if (normA === normB) continue; // equal titles share a title-hash key: already collapsed
      const contained = normA.includes(normB) || normB.includes(normA);
      const similarity = jaccard(titleTokenSet(normA), titleTokenSet(normB));
      if (contained || similarity >= TITLE_COLLISION_MIN_JACCARD) {
        collisions.push({
          left: si.seedIdentityKey(idless[i]),
          right: si.seedIdentityKey(idless[j]),
          leftTitle: idless[i].title,
          rightTitle: idless[j].title,
          reason:
            'both seeds lack a stable identifier and their normalized titles are similar but ' +
            'NOT equal — kept DISTINCT (this skill refuses to fuzzy-merge); confirm whether ' +
            'they are the same paper and, if so, supply one seed with a DOI/PMID/arXiv id',
        });
      }
    }
  }

  return { seeds: Object.freeze([...kept]), merges: [...mergesByKey.values()], collisions };
}

/**
 * Deterministic SNOWBALL-layer merge of per-seed snowball results into ONE combined
 * result that PRISMA advances from exactly once.
 *
 * Identity here is EXACT paperId equality — the catalog's own identity, no string
 * similarity anywhere:
 *
 *   - candidates: first occurrence per paperId across runs (run order), then ranked
 *     once with the committed deterministic rankCandidates;
 *   - a paper that is a candidate in ANY run is a candidate in the merge (candidate
 *     wins over a stale per-run exclusion of the same paperId);
 *   - graph nodes/edges: first occurrence per paperId / per (source, target) pair;
 *   - seed attribution: each run's seed paper is its result's FIRST graph node
 *     (performSnowballSearch inserts the seed before any reference and throws when
 *     the seed cannot be fetched). Runs whose seeds resolve to the SAME paperId merge,
 *     attributed to the highest-precedence seed identity, recorded in `seedMerges`.
 *
 * For a single run the merge is the identity transform on every observable output —
 * what test/seed-golden-single.test.mjs pins byte-for-byte.
 *
 * @param {Array<{ seed: object, entityId: string, result: object }>} runs Per-seed
 *   performSnowballSearch results, in canonical seed order.
 * @param {object} whitelist The venue whitelist rankCandidates consumes.
 * @returns {{ graph: { nodes: object[], edges: object[] }, prismaExclusions: object,
 *   candidates: object[], mermaid: string,
 *   seedPapers: Array<{ seed: object, paperId: string, paper: object|null }>,
 *   seedMerges: Array<{ paperId: string, kept: string, absorbed: string[] }> }}
 */
export function mergeSnowballResults(runs, whitelist) {
  if (!Array.isArray(runs) || runs.length === 0) {
    throw new TypeError('mergeSnowballResults: runs must be a non-empty array of per-seed results');
  }
  for (const run of runs) {
    if (!run?.result?.graph?.nodes?.length) {
      throw new TypeError(
        'mergeSnowballResults: every run must carry a performSnowballSearch result with at least the seed node',
      );
    }
  }

  const candidateById = new Map();
  for (const run of runs) {
    for (const cand of run.result.candidates) {
      if (!candidateById.has(cand.paperId)) candidateById.set(cand.paperId, cand);
    }
  }

  const nodes = [];
  const nodeIds = new Set();
  for (const run of runs) {
    for (const node of run.result.graph.nodes) {
      if (nodeIds.has(node.paperId)) continue;
      nodeIds.add(node.paperId);
      nodes.push(
        candidateById.has(node.paperId) && node.status !== 'included'
          ? { ...node, status: 'included', reason: null }
          : node,
      );
    }
  }

  const edges = [];
  const edgeKeys = new Set();
  for (const run of runs) {
    for (const edge of run.result.graph.edges) {
      const key = `${edge.source} ${edge.target}`;
      if (edgeKeys.has(key)) continue;
      edgeKeys.add(key);
      edges.push(edge);
    }
  }

  const exclusions = [];
  const excludedIds = new Set();
  for (const run of runs) {
    for (const exclusion of run.result.prismaExclusions.exclusions) {
      if (candidateById.has(exclusion.paperId) || excludedIds.has(exclusion.paperId)) continue;
      excludedIds.add(exclusion.paperId);
      exclusions.push(exclusion);
    }
  }

  const runsBySeedPaper = new Map();
  for (const run of runs) {
    const seedPaperId = run.result.graph.nodes[0].paperId;
    if (!runsBySeedPaper.has(seedPaperId)) runsBySeedPaper.set(seedPaperId, []);
    runsBySeedPaper.get(seedPaperId).push(run);
  }
  const seedPapers = [];
  const seedMerges = [];
  for (const [paperId, group] of runsBySeedPaper) {
    const ordered = [...group].sort((a, b) => compareByPrecedence(a.seed, b.seed));
    const keptRun = ordered[0];
    if (group.length > 1) {
      seedMerges.push({
        paperId,
        kept: `${keptRun.seed.idType}:${keptRun.seed.id}`,
        absorbed: ordered.slice(1).map((r) => `${r.seed.idType}:${r.seed.id}`),
      });
    }
    seedPapers.push({ seed: keptRun.seed, paperId, paper: candidateById.get(paperId) ?? null });
  }

  const candidates = rankCandidates([...candidateById.values()], whitelist);
  const prismaExclusions = { exclusions };
  validateSchema(prismaExclusions, 'PrismaExclusions');
  const mermaid = generateMermaidGraph(nodes, edges);

  return { graph: { nodes, edges }, prismaExclusions, candidates, mermaid, seedPapers, seedMerges };
}

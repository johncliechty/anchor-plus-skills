// src/candidate-assembly.mjs — Wave 1 (2026-09-04, journal 0010): Seeds always in.
//
// The 0010 run lost ten of twelve user seeds at ONE line: the merged snowball
// candidates were rank-truncated to the N most cited, and hand-picked seeds competed
// on citation count against field-generic giants (Fiji, U-Net, NumPy) — and lost.
// This module makes every user-supplied seed a CANONICAL, RELEVANCE-EXEMPT candidate
// before rank truncation:
//
//   - the canonical candidate record carries stable identity (canonical_id: the
//     catalog paperId when resolved, the seed's idType:id key otherwise), seed
//     status (is_seed / seed_identity), relevance exemption (relevance_exempt — the
//     Wave-3 relevance floor must never exclude a seed), and the text-sourcing
//     stamps (text_source / text_source_attempts — null/empty until the Wave-2
//     sourcing chain fills them; nothing is invented here);
//   - seeds UPSERT by stable identity: a seed already among the candidates is
//     marked, never duplicated; duplicate representations of one paper (a DOI seed
//     and a PMID seed resolving to the same paperId) land on ONE record, attributed
//     to the highest-precedence identity (the mergeSnowballResults attribution),
//     invariant to seed input order;
//   - rank truncation is seed-preserving: seeds are retained regardless of citation
//     rank; non-seeds fill the remaining budget in rank order, and every dropped
//     non-seed is recorded (stamped, never silent);
//   - every seed emits a PRISMA inclusion record (schema-validated) — the inclusion
//     mirror of the committed PRISMA exclusion log.
//
// Everything here is pure and deterministic: no network, no model, no clock.

import { validateSchema } from './validateSchema.mjs';

export const CANDIDATE_ASSEMBLY_VERSION = 'litreview-candidate-assembly/1';

/**
 * The `idType:id` identity key of a validated seed — the same key convention
 * seed-identity.mjs records in merges/collisions (e.g. 'doi:10.1000/x').
 *
 * @param {{ idType: string, id: string }} seed
 * @returns {string}
 */
export function seedIdentityKeyOf(seed) {
  if (typeof seed !== 'object' || seed === null || typeof seed.idType !== 'string' || typeof seed.id !== 'string') {
    throw new TypeError('seedIdentityKeyOf: seed must be a validated { idType, id } object');
  }
  return `${seed.idType}:${seed.id}`;
}

/**
 * Normalize one paper into the canonical candidate record. Preserves every field the
 * paper already carries (downstream stages keep reading title/abstract/citationCount
 * unchanged) and adds the Wave-1 fields:
 *
 *   canonical_id          stable identity: catalog paperId, else the seed's idType:id key
 *   is_seed               user-supplied seed status
 *   seed_identity         the seed's idType:id key (null for non-seeds)
 *   relevance_exempt      seeds are exempt from the relevance floor by construction
 *   text_source           the sourcing-chain link that supplied text (null until Wave 2 runs the chain)
 *   text_source_attempts  the chain's structured attempts (empty until Wave 2)
 *
 * Idempotent: re-canonicalizing a canonical record changes nothing.
 *
 * @param {object} paper A snowball/candidate paper (or a seed-derived stub).
 * @param {{ seed?: { idType: string, id: string }|null }} [options] The seed this
 *   record represents, when it is a seed record.
 * @returns {object} the canonical candidate record (a new object)
 */
export function toCanonicalCandidate(paper, { seed = null } = {}) {
  if (paper === null || typeof paper !== 'object') {
    throw new TypeError('toCanonicalCandidate: paper must be an object');
  }
  const paperId = typeof paper.paperId === 'string' && paper.paperId !== '' ? paper.paperId : null;
  const canonicalId = paperId ?? (seed !== null ? seedIdentityKeyOf(seed) : null);
  if (canonicalId === null) {
    throw new TypeError(
      'toCanonicalCandidate: a candidate needs a stable identity — a catalog paperId, or a seed idType:id key',
    );
  }
  const isSeed = seed !== null || paper.is_seed === true;
  return {
    ...paper,
    paperId: paperId ?? canonicalId,
    canonical_id: canonicalId,
    is_seed: isSeed,
    seed_identity:
      seed !== null ? seedIdentityKeyOf(seed) : typeof paper.seed_identity === 'string' ? paper.seed_identity : null,
    relevance_exempt: isSeed || paper.relevance_exempt === true,
    text_source: typeof paper.text_source === 'string' ? paper.text_source : null,
    text_source_attempts: Array.isArray(paper.text_source_attempts) ? [...paper.text_source_attempts] : [],
  };
}

/**
 * Assemble the canonical candidate list: every merged snowball candidate becomes a
 * canonical record (ranked order preserved), then EVERY user-supplied seed is
 * upserted by stable identity:
 *
 *   - a seed whose resolved paperId is already a candidate MARKS that record
 *     (is_seed / relevance_exempt / seed_identity) — never a second record;
 *   - duplicate representations of one paper converge on ONE record whose
 *     seed_identity is the highest-precedence key mergeSnowballResults attributed
 *     (order-invariant across seed input orderings);
 *   - a seed with no resolved candidate (rank-dropped elsewhere, snowball-skipped
 *     title-hash, both-providers-dead pre-flight) is INSERTED as a canonical record
 *     built from its resolved paper metadata when available, else from the seed
 *     itself (identity = its idType:id key) — in the corpus by construction.
 *
 * @param {object} options
 * @param {object[]} [options.candidates] mergeSnowballResults' ranked candidates.
 * @param {object[]} [options.seeds] The FULL canonical user seed list (the approved
 *   PlanArtifact.seeds — including seeds snowball skipped).
 * @param {Array<{ seed: object, paperId: string, paper: object|null }>} [options.seedPapers]
 *   mergeSnowballResults' per-resolved-paper seed attribution.
 * @param {Array<{ paperId: string, kept: string, absorbed: string[] }>} [options.seedMerges]
 *   mergeSnowballResults' duplicate-representation record (absorbed keys resolve here too).
 * @returns {{ candidates: object[], seedUpserts: Array<{ canonical_id: string,
 *   seed_identity: string, action: 'marked-existing'|'inserted' }> }}
 */
export function assembleCandidatesWithSeeds({ candidates = [], seeds = [], seedPapers = [], seedMerges = [] } = {}) {
  if (!Array.isArray(candidates) || !Array.isArray(seeds)) {
    throw new TypeError('assembleCandidatesWithSeeds: candidates and seeds must be arrays');
  }

  const byId = new Map(); // canonical_id -> record, insertion order = ranked order then inserted-seed order
  for (const paper of candidates) {
    const rec = toCanonicalCandidate(paper);
    if (!byId.has(rec.canonical_id)) byId.set(rec.canonical_id, rec);
  }

  // Resolution map: every seed representation (kept AND absorbed) -> resolved catalog
  // paperId. Attribution map: resolved paperId -> the KEPT (highest-precedence) key.
  const resolvedKeyToPaperId = new Map();
  const attributionByPaperId = new Map();
  const paperByPaperId = new Map();
  for (const sp of Array.isArray(seedPapers) ? seedPapers : []) {
    if (!sp || typeof sp.paperId !== 'string' || sp.paperId === '') continue;
    if (sp.seed) {
      const key = seedIdentityKeyOf(sp.seed);
      resolvedKeyToPaperId.set(key, sp.paperId);
      if (!attributionByPaperId.has(sp.paperId)) attributionByPaperId.set(sp.paperId, key);
    }
    if (sp.paper && !paperByPaperId.has(sp.paperId)) paperByPaperId.set(sp.paperId, sp.paper);
  }
  for (const m of Array.isArray(seedMerges) ? seedMerges : []) {
    if (!m || typeof m.paperId !== 'string') continue;
    if (typeof m.kept === 'string') resolvedKeyToPaperId.set(m.kept, m.paperId);
    for (const key of Array.isArray(m.absorbed) ? m.absorbed : []) {
      resolvedKeyToPaperId.set(key, m.paperId);
    }
  }

  const seedUpserts = [];
  for (const seed of seeds) {
    const key = seedIdentityKeyOf(seed);
    const canonicalId = resolvedKeyToPaperId.get(key) ?? key;
    const seedIdentity = attributionByPaperId.get(canonicalId) ?? key;
    const existing = byId.get(canonicalId);
    if (existing) {
      existing.is_seed = true;
      existing.relevance_exempt = true;
      existing.seed_identity = seedIdentity;
      seedUpserts.push({ canonical_id: canonicalId, seed_identity: key, action: 'marked-existing' });
    } else {
      const base = paperByPaperId.get(canonicalId) ?? {
        paperId: canonicalId,
        title: typeof seed.title === 'string' && seed.title !== '' ? seed.title : 'Untitled',
        venue: 'Unknown',
        year: null,
        citationCount: 0,
        authors: [],
        abstract: typeof seed.abstract === 'string' ? seed.abstract : null,
        provider: 'user-seed',
      };
      const rec = toCanonicalCandidate(base, { seed });
      rec.seed_identity = seedIdentity;
      byId.set(rec.canonical_id, rec);
      seedUpserts.push({ canonical_id: rec.canonical_id, seed_identity: key, action: 'inserted' });
    }
  }

  return { candidates: [...byId.values()], seedUpserts };
}

/**
 * Seed-preserving rank truncation — the fix for the exact 0010 kill line
 * (`candidates.slice(0, maxPapers)` dropped ten of twelve seeds). Seeds are retained
 * REGARDLESS of rank; non-seeds fill the remaining budget in list (rank) order, so
 * the total kept is max(maxPapers, seed count) at most. Order is preserved; every
 * dropped non-seed is recorded.
 *
 * @param {object[]} candidates Canonical candidate records, ranked.
 * @param {number} maxPapers The operator's extraction budget (non-negative integer).
 * @returns {{ kept: object[], dropped: Array<{ paperId: string|null, title: string,
 *   reason: 'rank-truncated' }>, seedCount: number, nonSeedBudget: number }}
 */
export function truncateCandidatesPreservingSeeds(candidates, maxPapers) {
  if (!Array.isArray(candidates)) {
    throw new TypeError('truncateCandidatesPreservingSeeds: candidates must be an array');
  }
  if (!Number.isInteger(maxPapers) || maxPapers < 0) {
    throw new TypeError('truncateCandidatesPreservingSeeds: maxPapers must be a non-negative integer');
  }
  const seedCount = candidates.reduce((n, c) => n + (c?.is_seed === true ? 1 : 0), 0);
  const nonSeedBudget = Math.max(maxPapers - seedCount, 0);
  const kept = [];
  const dropped = [];
  let nonSeedsKept = 0;
  for (const c of candidates) {
    if (c?.is_seed === true) {
      kept.push(c);
    } else if (nonSeedsKept < nonSeedBudget) {
      kept.push(c);
      nonSeedsKept += 1;
    } else {
      dropped.push({
        paperId: c?.canonical_id ?? c?.paperId ?? null,
        title: typeof c?.title === 'string' ? c.title : 'Untitled',
        reason: 'rank-truncated',
      });
    }
  }
  return { kept, dropped, seedCount, nonSeedBudget };
}

/**
 * PRISMA exclusion rows for the non-seeds the extraction budget dropped — every
 * exclusion is a logged reason, and rank truncation is an exclusion (the Gandalf
 * read of the build, 2026-09-04: drops were a console line only).
 *
 * @param {Array<{paperId: string|null, title: string, reason: string}>} dropped
 * @param {{ maxPapers: number, seedCount: number }} budget
 * @returns {{ exclusions: object[] }} A PrismaExclusions record (schema-validated).
 */
export function truncationPrismaExclusions(dropped, { maxPapers, seedCount }) {
  const exclusions = (Array.isArray(dropped) ? dropped : []).map((d) => ({
    paperId: String(d?.paperId ?? 'unknown'),
    title: typeof d?.title === 'string' ? d.title : 'Untitled',
    reason: 'rank-truncated',
    details: `ranked below the extraction budget (max-papers ${maxPapers}; ${seedCount} seed(s) kept first) by combined relevance × citation score`,
  }));
  const record = { exclusions };
  validateSchema(record, 'PrismaExclusions');
  return record;
}

/**
 * One PRISMA inclusion record per seed in the assembled candidate list — the
 * inclusion mirror of the PRISMA exclusion log, schema-validated (PrismaInclusions).
 *
 * @param {object[]} candidates Canonical candidate records (post-assembly).
 * @returns {{ inclusions: Array<{ paperId: string, title: string, reason: 'user-seed',
 *   relevance_exempt: boolean, seed_identity: string|null, details: string }> }}
 */
export function buildSeedPrismaInclusions(candidates) {
  if (!Array.isArray(candidates)) {
    throw new TypeError('buildSeedPrismaInclusions: candidates must be an array');
  }
  const inclusions = candidates
    .filter((c) => c?.is_seed === true)
    .map((c) => ({
      paperId: String(c.canonical_id ?? c.paperId),
      title: typeof c.title === 'string' && c.title !== '' ? c.title : 'Untitled',
      reason: 'user-seed',
      relevance_exempt: c.relevance_exempt === true,
      seed_identity: typeof c.seed_identity === 'string' ? c.seed_identity : null,
      details: 'user-supplied seed — in the corpus by construction; exempt from rank truncation and the relevance floor',
    }));
  const record = { inclusions };
  validateSchema(record, 'PrismaInclusions');
  return record;
}

// src/relevance.mjs — Wave 3 (2026-09-04, journal 0010): relevance-ranked, off-topic excluded.
//
// The 0010 run kept the 14 most-cited snowball candidates and extracted Fiji,
// PointNet++ and a shape GAN when the question was learned bases for 3D microscopy
// compression: candidate order was CITATIONS ALONE, and nothing ever asked whether a
// candidate was about the question. This module adds the missing relevance term —
// pure JS, deterministic, no network, no model, no new dependency:
//
//   - TF-IDF cosine similarity over normalized title + abstract text, with explicit
//     title weighting (DEFAULT_TITLE_WEIGHT — titles are the highest-signal text and
//     the plan's mitigation for short, noisy abstracts);
//   - every candidate is stamped with `relevance_score` (max cosine against the
//     scoreable seed set; a seed is compared against the OTHER seeds, never itself)
//     and `nearest_seed` (the canonical id of the seed it is closest to);
//   - citation weight is normalized deterministically (log-scaled against the list
//     maximum) and combined with relevance under DEFAULT_RANK_WEIGHTS; ordering ties
//     break on stable identity (canonical_id ascending), then original list order;
//   - a configurable `relevance_floor` is ACTIVE ONLY when scoreable seeds exist:
//     below-floor non-seeds are EXCLUDED before extraction and synthesis input, each
//     recorded as a PRISMA `off-topic` exclusion carrying its score, the floor, and
//     its nearest seed. Seeds are exempt by construction (relevance_exempt) — a seed
//     below the floor or lacking text is always retained.
//
// Stable behavior for the edges the plan names: a candidate with no scoreable text
// scores 0 (nearest_seed null, detail honest); a run with no seeds (or none with
// text) scores every candidate null, deactivates the floor, and ranks by citation
// weight alone — the pre-Wave-3 order, unchanged.

import { validateSchema } from './validateSchema.mjs';

export const RELEVANCE_VERSION = 'litreview-relevance/1';

/** Title tokens count this many times an abstract token — the plan's explicit title weighting. */
export const DEFAULT_TITLE_WEIGHT = 3;

/** The configurable hard relevance floor (cosine in [0,1]); active only when scoreable seeds exist. */
export const DEFAULT_RELEVANCE_FLOOR = 0.1;

/** Combined-rank weights: relevance dominates — citations alone are the exact 0010 failure. */
export const DEFAULT_RANK_WEIGHTS = Object.freeze({ relevance: 0.7, citation: 0.3 });

/** Round to 6 decimals at the stamping boundary: what is recorded is what is compared. */
const round6 = (x) => Math.round(x * 1e6) / 1e6;

/**
 * Deterministic normalization for relevance text: lowercase, fold diacritics,
 * split on non-alphanumeric runs, keep tokens of 2+ chars. No stemming, no
 * stopword list — IDF zeroes ubiquitous terms by construction (ln(N/df) = 0 at df=N).
 *
 * @param {unknown} text
 * @returns {string[]}
 */
export function relevanceTokensOf(text) {
  if (typeof text !== 'string') return [];
  return text
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 2);
}

/** Weighted term counts for one candidate: title tokens × titleWeight + abstract tokens × 1. */
function weightedTermCounts(candidate, titleWeight) {
  const counts = new Map();
  const add = (tokens, weight) => {
    for (const t of tokens) counts.set(t, (counts.get(t) ?? 0) + weight);
  };
  add(relevanceTokensOf(candidate?.title), titleWeight);
  add(relevanceTokensOf(candidate?.abstract), 1);
  return counts;
}

/** IDF over the candidate corpus: ln(N/df). A term in every document weighs zero. */
function inverseDocumentFrequencies(docs) {
  const df = new Map();
  for (const counts of docs) {
    for (const term of counts.keys()) df.set(term, (df.get(term) ?? 0) + 1);
  }
  const n = docs.length;
  const idf = new Map();
  for (const [term, d] of df) idf.set(term, Math.log(n / d));
  return idf;
}

/** TF-IDF vector + Euclidean norm for one document's weighted counts. */
function tfIdfVector(counts, idf) {
  const vec = new Map();
  let normSquared = 0;
  for (const [term, tf] of counts) {
    const w = tf * (idf.get(term) ?? 0);
    if (w > 0) {
      vec.set(term, w);
      normSquared += w * w;
    }
  }
  return { vec, norm: Math.sqrt(normSquared) };
}

/** Cosine similarity of two TF-IDF vectors; 0 whenever either side has no mass. */
function cosineSimilarity(a, b) {
  if (a.norm === 0 || b.norm === 0) return 0;
  const [small, large] = a.vec.size <= b.vec.size ? [a, b] : [b, a];
  let dot = 0;
  for (const [term, w] of small.vec) {
    const other = large.vec.get(term);
    if (other !== undefined) dot += w * other;
  }
  return dot / (a.norm * b.norm);
}

/** A candidate's stable identity, matching candidate-assembly's convention. */
function canonicalIdOf(candidate) {
  return String(candidate?.canonical_id ?? candidate?.paperId ?? '');
}

/**
 * Deterministic citation-weight normalization: log-scaled against the list maximum,
 * so the weight lands in [0,1] regardless of the corpus's citation magnitude. A list
 * with no citations at all weighs everything 0 (stable, never NaN).
 *
 * @param {unknown} citationCount
 * @param {unknown} maxCitationCount
 * @returns {number}
 */
export function normalizedCitationWeight(citationCount, maxCitationCount) {
  const c = Number.isFinite(citationCount) && citationCount > 0 ? citationCount : 0;
  const max = Number.isFinite(maxCitationCount) && maxCitationCount > 0 ? maxCitationCount : 0;
  if (max === 0) return 0;
  return round6(Math.log(1 + Math.min(c, max)) / Math.log(1 + max));
}

/**
 * Score and rank the candidate list: stamp every record with `relevance_score`,
 * `nearest_seed`, `citation_weight` and `combined_score`, then order by combined
 * score descending with stable tie-breakers (canonical_id ascending, then original
 * list position). Pure — returns new records; the input is untouched.
 *
 * Relevance is the max TF-IDF cosine against the scoreable seed documents (seeds
 * with at least one weighted token). A seed compares against the OTHER seeds only —
 * its score is an honest "how close to the rest of the seed set", never a vacuous
 * self-similarity 1.0. With no scoreable seeds the run carries no relevance signal:
 * every score is null, `floorApplicable` is false, and ranking is citation weight
 * alone (the pre-Wave-3 citation order, preserved).
 *
 * @param {object[]} candidates Canonical candidate records (candidate-assembly shape).
 * @param {object} [options]
 * @param {number} [options.titleWeight] Explicit title weighting (positive number).
 * @param {{ relevance: number, citation: number }} [options.weights] Combined-rank weights.
 * @returns {{ candidates: object[], floorApplicable: boolean }}
 */
export function rankCandidatesByRelevance(candidates, { titleWeight = DEFAULT_TITLE_WEIGHT, weights = DEFAULT_RANK_WEIGHTS } = {}) {
  if (!Array.isArray(candidates)) {
    throw new TypeError('rankCandidatesByRelevance: candidates must be an array');
  }
  if (!Number.isFinite(titleWeight) || titleWeight <= 0) {
    throw new TypeError(`rankCandidatesByRelevance: titleWeight must be a positive number, got ${JSON.stringify(titleWeight)}`);
  }
  if (
    weights === null || typeof weights !== 'object' ||
    !Number.isFinite(weights.relevance) || weights.relevance < 0 ||
    !Number.isFinite(weights.citation) || weights.citation < 0 ||
    weights.relevance + weights.citation <= 0
  ) {
    throw new TypeError('rankCandidatesByRelevance: weights must carry non-negative finite relevance/citation with a positive sum');
  }

  const docs = candidates.map((c) => {
    if (c === null || typeof c !== 'object') {
      throw new TypeError('rankCandidatesByRelevance: every candidate must be an object');
    }
    return weightedTermCounts(c, titleWeight);
  });
  const idf = inverseDocumentFrequencies(docs);
  const vectors = docs.map((counts) => tfIdfVector(counts, idf));

  const seedDocs = [];
  for (let i = 0; i < candidates.length; i++) {
    if (candidates[i].is_seed === true && vectors[i].norm > 0) {
      seedDocs.push({ index: i, id: canonicalIdOf(candidates[i]), vector: vectors[i] });
    }
  }
  const floorApplicable = seedDocs.length > 0;

  const maxCitations = candidates.reduce(
    (m, c) => (Number.isFinite(c.citationCount) && c.citationCount > m ? c.citationCount : m),
    0,
  );

  const stamped = candidates.map((c, i) => {
    let relevance = null;
    let nearest = null;
    if (floorApplicable) {
      const comparators = seedDocs.filter((s) => s.index !== i);
      if (comparators.length === 0) {
        // The lone scoreable seed has no other seed to compare against: null, stable.
        relevance = null;
      } else if (vectors[i].norm === 0) {
        // No scoreable text at all — a stable 0, never a crash, detail stays honest.
        relevance = 0;
      } else {
        let best = null;
        for (const s of comparators) {
          const cos = cosineSimilarity(vectors[i], s.vector);
          if (best === null || cos > best.cos) best = { cos, id: s.id };
        }
        relevance = round6(best.cos);
        nearest = best.cos > 0 ? best.id : null;
      }
    }
    const citationWeight = normalizedCitationWeight(c.citationCount, maxCitations);
    const combined = relevance === null
      ? citationWeight // no relevance signal for this record: citation order carries it
      : round6(weights.relevance * relevance + weights.citation * citationWeight);
    return {
      ...c,
      relevance_score: relevance,
      nearest_seed: nearest,
      // false when the record carries no scoreable title/abstract text at all (a
      // zero vector) — the screen labels such a record no-text, never off-topic
      relevance_scoreable: vectors[i].norm > 0,
      citation_weight: citationWeight,
      combined_score: combined,
    };
  });

  const ranked = stamped
    .map((rec, i) => ({ rec, i }))
    .sort((a, b) => {
      if (b.rec.combined_score !== a.rec.combined_score) return b.rec.combined_score - a.rec.combined_score;
      const aId = canonicalIdOf(a.rec);
      const bId = canonicalIdOf(b.rec);
      if (aId < bId) return -1;
      if (aId > bId) return 1;
      return a.i - b.i;
    })
    .map(({ rec }) => rec);

  return { candidates: ranked, floorApplicable };
}

/**
 * Screen a ranked candidate list at the relevance floor. Retention order is the
 * ranked order. A candidate is EXCLUDED only when the floor is active, it is not
 * relevance-exempt (seeds never are excludable), and its stamped score is below the
 * floor — recorded as a schema-validated PRISMA `off-topic` exclusion carrying the
 * score, the floor, and the nearest seed. An invalid floor is refused outright:
 * an unnamed bound cannot be tested.
 *
 * @param {object[]} rankedCandidates Records stamped by rankCandidatesByRelevance.
 * @param {object} [options]
 * @param {number} [options.relevanceFloor] Hard floor in [0,1].
 * @param {boolean} [options.floorActive] Whether scoreable seeds exist for this run.
 * @returns {{ retained: object[], excluded: object[],
 *   prismaExclusions: { exclusions: object[] }, relevance_floor: number, floor_active: boolean }}
 */
export function screenCandidatesAtRelevanceFloor(rankedCandidates, { relevanceFloor = DEFAULT_RELEVANCE_FLOOR, floorActive = true } = {}) {
  if (!Array.isArray(rankedCandidates)) {
    throw new TypeError('screenCandidatesAtRelevanceFloor: rankedCandidates must be an array');
  }
  if (!Number.isFinite(relevanceFloor) || relevanceFloor < 0 || relevanceFloor > 1) {
    throw new TypeError(
      `screenCandidatesAtRelevanceFloor: relevanceFloor must be a number in [0,1], got ${JSON.stringify(relevanceFloor)}`,
    );
  }

  const titlesById = new Map();
  for (const c of rankedCandidates) {
    titlesById.set(canonicalIdOf(c), typeof c?.title === 'string' && c.title !== '' ? c.title : 'Untitled');
  }

  const retained = [];
  const excluded = [];
  const exclusions = [];
  for (const c of rankedCandidates) {
    const exempt = c?.relevance_exempt === true || c?.is_seed === true;
    const score = typeof c?.relevance_score === 'number' ? c.relevance_score : null;
    if (!floorActive || exempt || score === null || score >= relevanceFloor) {
      retained.push(c);
      continue;
    }
    excluded.push(c);
    const nearest = typeof c.nearest_seed === 'string' ? c.nearest_seed : null;
    // A candidate with NO scoreable text (empty title + abstract → zero vector, no
    // nearest seed) is `no-text`, never `off-topic`: it was not judged, it could not
    // be judged (journal 0011's must-not; the Gandalf read of the build, 2026-09-04).
    const noText = c?.relevance_scoreable === false;
    exclusions.push({
      paperId: canonicalIdOf(c),
      title: titlesById.get(canonicalIdOf(c)),
      reason: noText ? 'no-text' : 'off-topic',
      relevance_score: score,
      relevance_floor: relevanceFloor,
      nearest_seed: nearest,
      details: noText
        ? `no scoreable text overlap with any seed: the candidate carries no title/abstract text to score, so it is excluded as no-text (not judged off-topic); floor ${relevanceFloor}`
        : nearest !== null
          ? `TF-IDF relevance ${score} is below the floor ${relevanceFloor}; nearest seed: "${titlesById.get(nearest) ?? nearest}" (${nearest})`
          : `TF-IDF relevance ${score} is below the floor ${relevanceFloor}; no scoreable text overlap with any seed`,
    });
  }

  const prismaExclusions = { exclusions };
  validateSchema(prismaExclusions, 'PrismaExclusions');
  return { retained, excluded, prismaExclusions, relevance_floor: relevanceFloor, floor_active: floorActive };
}

/**
 * The Wave-3 pipeline step in one call: rank (stamp scores), then screen at the
 * floor. This is what the CLI runs between candidate assembly and seed-preserving
 * truncation, so below-floor non-seeds never reach extraction or synthesis input.
 *
 * @param {object[]} candidates Canonical candidate records.
 * @param {object} [options]
 * @param {number} [options.titleWeight]
 * @param {{ relevance: number, citation: number }} [options.weights]
 * @param {number} [options.relevanceFloor]
 * @returns {{ candidates: object[], retained: object[], excluded: object[],
 *   prismaExclusions: { exclusions: object[] }, relevance_floor: number, floor_active: boolean }}
 */
export function applyRelevanceScreening(candidates, { titleWeight, weights, relevanceFloor = DEFAULT_RELEVANCE_FLOOR } = {}) {
  const rankOptions = {};
  if (titleWeight !== undefined) rankOptions.titleWeight = titleWeight;
  if (weights !== undefined) rankOptions.weights = weights;
  const ranked = rankCandidatesByRelevance(candidates, rankOptions);
  const screening = screenCandidatesAtRelevanceFloor(ranked.candidates, {
    relevanceFloor,
    floorActive: ranked.floorApplicable,
  });
  return { candidates: ranked.candidates, ...screening };
}

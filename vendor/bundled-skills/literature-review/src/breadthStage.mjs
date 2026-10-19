// src/breadthStage.mjs — Wave 2 + Wave 3: lit-review post-APPROVE breadth hook.
//
// Wave 2 (sequential base, still enforced):
//   • facetsFromPlan runs first after plan APPROVE and before main snowball;
//   • per-facet scoped gather uses one shared multi-seed set S plus the facet
//     question as a deterministic scope bias (NOT a |S|×|facets| cartesian);
//   • path is active only when plan status is APPROVED and facets.length ≥ 1;
//   • empty facets → honest breadth:none stamp, no invented work;
//   • plan not yet APPROVED → breadth gather does not run.
//
// Wave 3 (parallel + merge/dedupe):
//   • per-facet jobs scheduled via ConcurrencyManager (existing engine stack);
//   • default concurrency cap DEFAULT_FACET_CONCURRENCY (≤2–3);
//   • optional IsolatedWorker path via workerFactory (same stack as MatrixScheduler);
//   • per-facet failure isolation: failed facet stamps honest error; siblings complete;
//   • deterministic merge by facet.order then paper/source id;
//   • dedupe by exact paperId (lit-review stable catalog identity — no fuzzy merge).

import { facetsFromPlan } from './facetsFromPlan.mjs';
import { performSnowballSearch, DEFAULT_VENUE_WHITELIST } from './search.mjs';
import { seedEntityId, mergeSnowballResults } from './seed-identity.mjs';
import { ConcurrencyManager } from './concurrencyManager.mjs';
import { IsolatedWorker } from './isolatedWorker.mjs';

export const BREADTH_STAGE_VERSION = 'breadth-stage/2';

/** Pipeline plan status that unlocks the breadth path. */
export const BREADTH_REQUIRES_STATUS = 'APPROVED';

/**
 * Default per-facet concurrency cap (Wave 3): ≤2–3 concurrent facet workers.
 * Override via options.concurrency (still clamped to a positive integer).
 */
export const DEFAULT_FACET_CONCURRENCY = 2;

/**
 * Ordered event types emitted by runPostApproveBreadth (for ordering tests + telemetry).
 * @type {Readonly<{
 *   FACETS_MATERIALIZED: string,
 *   FACET_GATHER_START: string,
 *   FACET_GATHER_DONE: string,
 *   BREADTH_SKIPPED: string,
 *   BREADTH_COMPLETE: string,
 * }>}
 */
export const BREADTH_STAGE_EVENTS = Object.freeze({
  FACETS_MATERIALIZED: 'facets-materialized',
  FACET_GATHER_START: 'facet-gather-start',
  FACET_GATHER_DONE: 'facet-gather-done',
  BREADTH_SKIPPED: 'breadth-skipped',
  BREADTH_COMPLETE: 'breadth-complete',
});

/**
 * Freeze a multi-seed set S as a read-only snapshot shared across every facet gather.
 * Callers must not treat this as a per-facet private seed list (not |S|×|facets|).
 *
 * @param {unknown} seeds
 * @returns {ReadonlyArray<Readonly<object>>}
 */
export function freezeSharedSeeds(seeds) {
  if (!Array.isArray(seeds)) return Object.freeze([]);
  return Object.freeze(
    seeds.map((s) => {
      if (s != null && typeof s === 'object' && !Array.isArray(s)) {
        return Object.freeze({ ...s });
      }
      return Object.freeze({ value: s });
    }),
  );
}

/**
 * Tokenize free text for deterministic scope-bias scoring (alphanumeric, length > 2).
 * @param {unknown} text
 * @returns {Set<string>}
 */
function tokens(text) {
  return new Set(
    String(text ?? '')
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((t) => t.length > 2),
  );
}

/**
 * Score a paper against a facet question (token overlap of title + abstract).
 * @param {object} paper
 * @param {Set<string>} questionTokens
 * @returns {number}
 */
function scopeBiasScore(paper, questionTokens) {
  if (questionTokens.size === 0) return 0;
  const paperTokens = tokens(`${paper?.title ?? ''} ${paper?.abstract ?? ''}`);
  let hit = 0;
  for (const t of questionTokens) {
    if (paperTokens.has(t)) hit += 1;
  }
  return hit;
}

/**
 * Apply the facet question as a deterministic scope bias: re-rank candidates by
 * token overlap with the question (stable paperId tie-break). Does not invent papers
 * or drop them for missing overlap — bias is a ranking prior, like the venue whitelist.
 *
 * @param {ReadonlyArray<object>} candidates
 * @param {string} facetQuestion
 * @returns {ReadonlyArray<object>} Ranked hit records { paperId, title, year, abstract?, scopeBiasScore, scopeBiasRank, scopeBiasQuestion }
 */
export function applyScopeBias(candidates, facetQuestion) {
  const q = typeof facetQuestion === 'string' ? facetQuestion : '';
  const qTokens = tokens(q);
  const list = Array.isArray(candidates) ? candidates : [];
  const ranked = list
    .map((c, idx) => ({
      paperId: c?.paperId ?? null,
      title: c?.title ?? null,
      year: c?.year ?? null,
      abstract: c?.abstract ?? null,
      scopeBiasScore: scopeBiasScore(c, qTokens),
      _idx: idx,
    }))
    .sort((a, b) => {
      if (b.scopeBiasScore !== a.scopeBiasScore) return b.scopeBiasScore - a.scopeBiasScore;
      const idA = a.paperId == null ? '' : String(a.paperId);
      const idB = b.paperId == null ? '' : String(b.paperId);
      if (idA < idB) return -1;
      if (idA > idB) return 1;
      return a._idx - b._idx;
    });

  return Object.freeze(
    ranked.map((r, rank) =>
      Object.freeze({
        paperId: r.paperId,
        title: r.title,
        year: r.year,
        abstract: r.abstract,
        scopeBiasScore: r.scopeBiasScore,
        scopeBiasRank: rank,
        scopeBiasQuestion: q,
      }),
    ),
  );
}

/**
 * Default per-facet scoped gather: snowball every resolvable seed in the
 * shared multi-seed set S (same S for every facet), merge by paperId, then apply
 * facet.question as scope bias. Injectable alternatives may be passed to
 * runPostApproveBreadth for tests.
 *
 * @param {object} args
 * @param {{ id: string, question: string, order: number }} args.facet
 * @param {ReadonlyArray<object>} args.seeds Shared frozen multi-seed set S
 * @param {object} [args.options]
 * @returns {Promise<{ hits: ReadonlyArray<object>, seedCount: number, resolvableSeedCount: number, preBiasCount: number, scopeBias: string }>}
 */
export async function defaultScopedFacetGather({ facet, seeds, options = {} }) {
  const depth = options.depth ?? 1;
  const whitelist = options.whitelist ?? DEFAULT_VENUE_WHITELIST;
  const fetchImpl = options.fetch;
  const snowball = options.performSnowball ?? performSnowballSearch;
  const merge = options.mergeResults ?? mergeSnowballResults;

  const runs = [];
  for (const seed of seeds) {
    let entityId = null;
    try {
      entityId = seedEntityId(seed);
    } catch {
      entityId = null;
    }
    if (entityId == null) continue;
    const result = await snowball(entityId, whitelist, {
      depth,
      ...(fetchImpl ? { fetch: fetchImpl } : {}),
    });
    runs.push({ seed, entityId, result });
  }

  if (runs.length === 0) {
    return Object.freeze({
      hits: Object.freeze([]),
      seedCount: seeds.length,
      resolvableSeedCount: 0,
      preBiasCount: 0,
      scopeBias: facet.question,
    });
  }

  const merged = merge(runs, whitelist);
  const candidates = Array.isArray(merged.candidates) ? merged.candidates : [];
  const hits = applyScopeBias(candidates, facet.question);
  return Object.freeze({
    hits,
    seedCount: seeds.length,
    resolvableSeedCount: runs.length,
    preBiasCount: candidates.length,
    scopeBias: facet.question,
  });
}

/**
 * Resolve a positive integer concurrency cap; default DEFAULT_FACET_CONCURRENCY (2).
 * @param {unknown} value
 * @returns {number}
 */
export function resolveFacetConcurrency(value) {
  if (Number.isInteger(value) && value >= 1) return value;
  return DEFAULT_FACET_CONCURRENCY;
}

/**
 * Stable paper/source identity key for breadth corpus dedupe.
 * Exact paperId equality (catalog identity) — same refusal of fuzzy merge as
 * seed-identity.mjs / mergeSnowballResults. Null/missing ids get a synthetic
 * key so they never falsely collapse with each other.
 *
 * @param {object|null|undefined} hit
 * @param {number} fallbackIndex
 * @returns {string}
 */
export function paperIdentityKey(hit, fallbackIndex = 0) {
  if (hit != null && hit.paperId != null && String(hit.paperId).length > 0) {
    return `paperId:${String(hit.paperId)}`;
  }
  return `no-id:${fallbackIndex}`;
}

/**
 * Deterministic merge + dedupe of per-facet gather hits into one corpus.
 *
 * Merge order: facet.order ascending, then paperId ascending within a facet.
 * Dedupe: first occurrence of each stable paperId wins (exact identity only).
 * Failed facets (error set / empty hits) contribute nothing to the corpus.
 *
 * @param {ReadonlyArray<object>} facetResults Records from runPostApproveBreadth
 * @returns {{
 *   entries: ReadonlyArray<object>,
 *   merges: ReadonlyArray<{ paperId: string, keptFacetId: string, absorbedFacetIds: ReadonlyArray<string> }>,
 *   totalHitsSeen: number,
 *   uniqueCount: number,
 * }}
 */
export function mergeBreadthCorpus(facetResults) {
  const results = Array.isArray(facetResults) ? [...facetResults] : [];
  results.sort((a, b) => {
    const oa = Number.isFinite(a?.order) ? a.order : 0;
    const ob = Number.isFinite(b?.order) ? b.order : 0;
    if (oa !== ob) return oa - ob;
    const idA = a?.facetId == null ? '' : String(a.facetId);
    const idB = b?.facetId == null ? '' : String(b.facetId);
    return idA < idB ? -1 : idA > idB ? 1 : 0;
  });

  /** @type {Array<{ hit: object, facetId: string, order: number, paperId: string|null }>} */
  const ordered = [];
  let totalHitsSeen = 0;
  for (const fr of results) {
    if (fr?.error) continue;
    const hits = Array.isArray(fr?.hits) ? fr.hits : [];
    const withKeys = hits.map((hit, idx) => ({
      hit,
      facetId: fr.facetId,
      order: fr.order,
      paperId: hit?.paperId == null ? null : hit.paperId,
      _sortId: paperIdentityKey(hit, idx),
      _idx: idx,
    }));
    withKeys.sort((a, b) => {
      if (a._sortId < b._sortId) return -1;
      if (a._sortId > b._sortId) return 1;
      return a._idx - b._idx;
    });
    for (const row of withKeys) {
      totalHitsSeen += 1;
      ordered.push(row);
    }
  }

  const seen = new Map();
  /** @type {object[]} */
  const entries = [];
  /** @type {Map<string, { paperId: string, keptFacetId: string, absorbed: string[] }>} */
  const mergeMap = new Map();

  for (const row of ordered) {
    const key = row.paperId == null ? row._sortId : `paperId:${String(row.paperId)}`;
    // Null paperIds never share a key across hits (each no-id:N is unique) —
    // only catalog paperIds dedupe.
    if (row.paperId != null && seen.has(key)) {
      const kept = seen.get(key);
      if (!mergeMap.has(key)) {
        mergeMap.set(key, {
          paperId: String(row.paperId),
          keptFacetId: kept.facetId,
          absorbed: [],
        });
      }
      const rec = mergeMap.get(key);
      if (!rec.absorbed.includes(row.facetId) && row.facetId !== rec.keptFacetId) {
        rec.absorbed.push(row.facetId);
      }
      continue;
    }
    if (row.paperId != null) {
      seen.set(key, { facetId: row.facetId, order: row.order });
    }
    entries.push(
      Object.freeze({
        paperId: row.paperId,
        title: row.hit?.title ?? null,
        year: row.hit?.year ?? null,
        abstract: row.hit?.abstract ?? null,
        scopeBiasScore: row.hit?.scopeBiasScore ?? null,
        scopeBiasRank: row.hit?.scopeBiasRank ?? null,
        scopeBiasQuestion: row.hit?.scopeBiasQuestion ?? null,
        sourceFacetId: row.facetId,
        sourceFacetOrder: row.order,
        // Preserve any extra hit fields that callers may have attached.
        ...(row.hit && typeof row.hit === 'object'
          ? Object.fromEntries(
              Object.entries(row.hit).filter(
                ([k]) =>
                  ![
                    'paperId',
                    'title',
                    'year',
                    'abstract',
                    'scopeBiasScore',
                    'scopeBiasRank',
                    'scopeBiasQuestion',
                  ].includes(k),
              ),
            )
          : {}),
      }),
    );
  }

  const merges = [...mergeMap.values()].map((m) =>
    Object.freeze({
      paperId: m.paperId,
      keptFacetId: m.keptFacetId,
      absorbedFacetIds: Object.freeze([...m.absorbed]),
    }),
  );
  merges.sort((a, b) => (a.paperId < b.paperId ? -1 : a.paperId > b.paperId ? 1 : 0));

  return Object.freeze({
    entries: Object.freeze(entries),
    merges: Object.freeze(merges),
    totalHitsSeen,
    uniqueCount: entries.length,
  });
}

/**
 * Empty corpus shape for skip / no-run outcomes.
 * @returns {ReturnType<typeof mergeBreadthCorpus>}
 */
function emptyCorpus() {
  return Object.freeze({
    entries: Object.freeze([]),
    merges: Object.freeze([]),
    totalHitsSeen: 0,
    uniqueCount: 0,
  });
}

/**
 * Build a facet-result record from a successful gather payload.
 * @param {object} facet
 * @param {object} gathered
 * @param {number} sharedSeedCount
 */
function successRecord(facet, gathered, sharedSeedCount) {
  const hits = Array.isArray(gathered?.hits) ? gathered.hits : [];
  return Object.freeze({
    facetId: facet.id,
    order: facet.order,
    question: facet.question,
    seedCount: gathered?.seedCount ?? sharedSeedCount,
    resolvableSeedCount: gathered?.resolvableSeedCount ?? null,
    preBiasCount: gathered?.preBiasCount ?? null,
    scopeBias: gathered?.scopeBias ?? facet.question,
    hits: Object.freeze([...hits]),
    error: null,
  });
}

/**
 * Build a facet-result record from a failure (honest error stamp).
 * @param {object} facet
 * @param {string} message
 * @param {number} sharedSeedCount
 */
function failureRecord(facet, message, sharedSeedCount) {
  return Object.freeze({
    facetId: facet.id,
    order: facet.order,
    question: facet.question,
    seedCount: sharedSeedCount,
    resolvableSeedCount: null,
    preBiasCount: null,
    scopeBias: facet.question,
    hits: Object.freeze([]),
    error: message,
  });
}

/**
 * Post-APPROVE breadth stage: materialize facets, then PARALLEL per-facet scoped
 * gather over shared S (ConcurrencyManager-capped; optional IsolatedWorker),
 * merge+dedupe into one corpus, completing before the caller's main snowball/depth.
 *
 * @param {object} args
 * @param {string|null|undefined} args.planStatus Pipeline plan status (`APPROVED` unlocks gather).
 * @param {object|null|undefined} args.plan Approved PlanArtifact (or plan-shaped object).
 * @param {ReadonlyArray<object>|null|undefined} args.seeds Multi-seed set S (shared across facets).
 * @param {(args: { facet: object, seeds: ReadonlyArray<object> }) => Promise<object>} [args.gatherFacet]
 *   Injectable per-facet gather. Defaults to defaultScopedFacetGather.
 *   When both gatherFacet and workerFactory are omitted and taskModule is set,
 *   each facet runs inside an IsolatedWorker (MatrixScheduler-style stack).
 * @param {object} [args.options] Forwarded to the default gather (depth, fetch, …).
 *   options.concurrency — max concurrent facet workers (default DEFAULT_FACET_CONCURRENCY).
 * @param {(msg: string) => void} [args.log]
 * @param {string} [args.taskModule] Absolute path to an IsolatedWorker task module.
 * @param {(opts: object) => { run: () => Promise<object>, workerId?: string }} [args.workerFactory]
 *   Injectable worker factory (tests / MatrixScheduler doubles). When provided,
 *   each facet is executed as workerFactory({ taskModule, input: { facet, seeds }, ... }).run().
 * @param {string[]} [args.allowlist] Network allowlist for IsolatedWorker (default []).
 * @param {number} [args.workerTimeoutMs] IsolatedWorker timeout (default 0 = none).
 * @returns {Promise<{
 *   version: string,
 *   ran: boolean,
 *   reason: string|null,
 *   stamp: string|null,
 *   facets: ReadonlyArray<object>,
 *   sharedSeeds: ReadonlyArray<object>,
 *   facetResults: ReadonlyArray<object>,
 *   corpus: ReturnType<typeof mergeBreadthCorpus>,
 *   concurrency: number,
 *   maxActive: number,
 *   events: ReadonlyArray<object>,
 * }>}
 */
export async function runPostApproveBreadth({
  planStatus,
  plan,
  seeds,
  gatherFacet,
  options = {},
  log = () => {},
  taskModule = null,
  workerFactory = null,
  allowlist = [],
  workerTimeoutMs = 0,
} = {}) {
  const events = [];
  const push = (type, payload = {}) => {
    events.push(Object.freeze({ type, ...payload }));
  };

  const skipBase = {
    version: BREADTH_STAGE_VERSION,
    ran: false,
    facets: Object.freeze([]),
    sharedSeeds: Object.freeze([]),
    facetResults: Object.freeze([]),
    corpus: emptyCorpus(),
    concurrency: resolveFacetConcurrency(options.concurrency),
    maxActive: 0,
  };

  // Gate: facet breadth gather does not run until the plan is APPROVED.
  if (planStatus !== BREADTH_REQUIRES_STATUS) {
    push(BREADTH_STAGE_EVENTS.BREADTH_SKIPPED, {
      reason: 'plan-not-approved',
      planStatus: planStatus ?? null,
    });
    log(
      `Breadth stage SKIPPED: plan status is ${JSON.stringify(planStatus)} (requires ${BREADTH_REQUIRES_STATUS}).`,
    );
    return Object.freeze({
      ...skipBase,
      reason: 'plan-not-approved',
      stamp: null,
      events: Object.freeze(events),
    });
  }

  // facetsFromPlan runs first (materialize before any gather / main snowball).
  const { facets, stamp } = facetsFromPlan(plan);
  push(BREADTH_STAGE_EVENTS.FACETS_MATERIALIZED, {
    stamp,
    facetCount: facets.length,
    facetIds: facets.map((f) => f.id),
  });
  log(`Breadth stage: facetsFromPlan → ${facets.length} facet(s), stamp ${stamp}.`);

  const sharedSeeds = freezeSharedSeeds(seeds ?? []);
  const concurrency = resolveFacetConcurrency(options.concurrency);

  if (facets.length === 0) {
    // Honest no-breadth stamp; no invented facets; existing non-breadth path proceeds.
    push(BREADTH_STAGE_EVENTS.BREADTH_SKIPPED, {
      reason: 'no-facets',
      stamp,
    });
    log(`Breadth stage: empty facets (${stamp}) — no gather; existing single path continues.`);
    return Object.freeze({
      ...skipBase,
      reason: 'no-facets',
      stamp,
      sharedSeeds,
      concurrency,
      events: Object.freeze(events),
    });
  }

  // Worker stack (MatrixScheduler-style): optional IsolatedWorker / injectable factory.
  // When neither workerFactory nor taskModule is set, gather runs in-process under the
  // ConcurrencyManager cap (still parallel, still failure-isolated).
  const factory =
    typeof workerFactory === 'function'
      ? workerFactory
      : typeof taskModule === 'string' && taskModule.length > 0
        ? (opts) => new IsolatedWorker(opts)
        : null;

  const gather =
    typeof gatherFacet === 'function'
      ? gatherFacet
      : (args) => defaultScopedFacetGather({ ...args, options });

  const manager = new ConcurrencyManager({ limit: concurrency });
  log(
    `Breadth stage: parallel per-facet gather (concurrency cap ${concurrency}` +
      (factory ? ', isolated-worker stack' : '') +
      `) over ${sharedSeeds.length} shared seed(s).`,
  );

  // Schedule every facet under the concurrency cap; failures are isolated per facet.
  const settled = await Promise.all(
    facets.map((facet) =>
      manager.run(async () => {
        push(BREADTH_STAGE_EVENTS.FACET_GATHER_START, {
          facetId: facet.id,
          order: facet.order,
          question: facet.question,
          seedCount: sharedSeeds.length,
        });
        log(
          `  breadth facet ${facet.id} (order ${facet.order}): parallel scoped gather over ${sharedSeeds.length} shared seed(s); scope bias = ${JSON.stringify(facet.question)}`,
        );

        try {
          let gathered;
          if (factory) {
            const worker = factory({
              taskModule: taskModule ?? 'inline-facet-gather',
              input: { facet, seeds: sharedSeeds, options },
              allowlist: [...allowlist],
              timeoutMs: workerTimeoutMs,
            });
            gathered = await worker.run();
          } else {
            gathered = await gather({ facet, seeds: sharedSeeds });
          }

          const record = successRecord(facet, gathered, sharedSeeds.length);
          push(BREADTH_STAGE_EVENTS.FACET_GATHER_DONE, {
            facetId: facet.id,
            hitCount: record.hits.length,
            error: null,
          });
          return record;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          const record = failureRecord(facet, message, sharedSeeds.length);
          push(BREADTH_STAGE_EVENTS.FACET_GATHER_DONE, {
            facetId: facet.id,
            hitCount: 0,
            error: message,
          });
          log(`  breadth facet ${facet.id} FAILED (honest): ${message}`);
          return record;
        }
      }),
    ),
  );

  // Deterministic facetResults order by facet.order (not completion order).
  const facetResults = [...settled].sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    const idA = a.facetId == null ? '' : String(a.facetId);
    const idB = b.facetId == null ? '' : String(b.facetId);
    return idA < idB ? -1 : idA > idB ? 1 : 0;
  });

  const corpus = mergeBreadthCorpus(facetResults);

  push(BREADTH_STAGE_EVENTS.BREADTH_COMPLETE, {
    stamp,
    facetCount: facets.length,
    sharedSeedCount: sharedSeeds.length,
    corpusUniqueCount: corpus.uniqueCount,
    corpusMerges: corpus.merges.length,
    concurrency,
    maxActive: manager.maxActive,
  });
  log(
    `Breadth stage COMPLETE (${stamp}) — corpus ${corpus.uniqueCount} unique paper(s) from ${corpus.totalHitsSeen} hit(s); main snowball/depth may proceed.`,
  );

  return Object.freeze({
    version: BREADTH_STAGE_VERSION,
    ran: true,
    reason: null,
    stamp,
    facets: Object.freeze([...facets]),
    sharedSeeds,
    facetResults: Object.freeze(facetResults),
    corpus,
    concurrency,
    maxActive: manager.maxActive,
    events: Object.freeze(events),
  });
}

export default runPostApproveBreadth;

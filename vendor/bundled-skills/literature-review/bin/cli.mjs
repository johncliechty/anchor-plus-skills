#!/usr/bin/env node
// literature-review CLI — REWIRED REAL (C8, 2026-07-11, John's decision).
//
// History: the original production path injected mock agents into every LLM seat,
// seeded dummy ledgers, called the runEngine skeleton researchPrime forbids, and
// printed fabricated success (deleted 2026-07-11 as hazard A3). This rewire binds
// REAL seats:
//   - deterministic stages unchanged: ingest → snowball (venue = ranking prior, not
//     an exclusion) → PRISMA log → mixed-initiative gate (TTY-aware);
//   - LEAN extraction: ONE model call per paper + a DETERMINISTIC quote-grounding
//     check (fabricated support dies on a string match) — not the per-chunk shark
//     court (~1000s of calls) the original design demanded;
//   - final ADVERSARIAL pass over the SYNTHESIZED cross-paper ledger through
//     researchPrime's REAL surface (runGovernedRound: trio ≥2-agree tally, claim_id
//     identity, inclusion test) — one governed round, honestly stamped as such;
//   - live model seats via researchPrime's live-round-agent (5:1: reviewers/judge →
//     Gemini/agy, extraction/synthesizer/copilot → Claude). No live seats bound ⇒
//     the run STOPS after the deterministic stages with an explicit stamp. Nothing
//     is ever fabricated.
//
// Usage:
//   node bin/cli.mjs [--seed <spec>]... [--seed-list <json-file>] [--depth N]
//        [--max-papers N] [--columns a,b,c] [--stakes low|medium|high] [--out <dir>]
//        [--mock-user "q: ...|approve"] [--live]
//        [--content <root>]... [--intent "<research intent>"] [--plan-run-dir <dir>]
//        [--plan-decision APPROVE|EDIT|ABORT] [--plan-edited-file <path>]
//        [--plan-token <token>] [--plan-policy-grant <identity>]
//   Seed specs (Wave 10 — replacing the single --seed <pdf-url>): doi:<id>[|title],
//   pmid:<id>[|title], arxiv:<id>[|title], title:<title>, a doi.org / arxiv.org/abs
//   identifier URL, or a bare DOI/PMID/arXiv id; anything else is a title-only seed.
//   LITREVIEW_LIVE=1 (or --live): bind the real cross-family seats (requires agy for
//   the reviewer/judge seats; HALTs honestly if down).
//
// Wave 9 (Stage-0 PLAN phase): when --content and/or --intent is given, the run is
// plan-first — the shared brownfield-intake front-end derives a PlanArtifact, the
// FROZEN researchPrime one-shot gate presents it (APPROVE/EDIT/ABORT), and the run
// HALTs with fully-serialized pipeline state BEFORE the snowball stage. Snowball is
// unlocked ONLY by stage0AllowsExecution(); a halted run resumes with the SAME
// command plus a decision flag (or a headless --plan-token / --plan-policy-grant),
// spending zero additional intake LLM calls.
//
// Wave 10 (multi-seed injection): the canonical seed list flows CLI (seed-adapter:
// strict validation before any child-process handoff, deterministic list dedupe) ->
// Stage-0 intake -> PlanArtifact.seeds -> gate prose -> snowball/PRISMA. A seeds-only
// invocation takes the shared module's DETERMINISTIC seeds-only bootstrap route (zero
// LLM calls), so it needs no live seats to reach the gate. After APPROVE, snowball
// consumes seeds ONLY from the approved artifact's seeds field — never from the CLI
// args, and never re-derived — and per-seed results merge by exact paperId identity
// (deterministic cross-seed dedupe, no fuzzy merge) before PRISMA advances once.
//
// Wave 2–3 (2D breadth hook): after Stage-0 APPROVE and before the main multi-seed
// snowball, runPostApproveBreadth materializes facets via facetsFromPlan and —
// when facets.length ≥ 1 — runs PARALLEL per-facet scoped gathers (ConcurrencyManager
// cap ≤2–3; optional IsolatedWorker stack) over the shared multi-seed set S
// (facet.question as scope bias; not |S|×|facets|), then merge+dedupe by exact
// paperId into one corpus (order: facet.order then paper id). Empty facets stamp
// breadth:none honestly and leave the existing single path unchanged.
//
// Wave 5 (honesty stamps + telemetry + seat hygiene): every breadth outcome is
// projected into a pure breadthTelemetry record (stamp / facet errors /
// incompleteCoverage / funnel) written into breadth-stage.json and journal/runs;
// review multi-agree lineage uses gemini-cli labels only (no API-style Gemini
// product ids). LITREVIEW_LIVE degraded posture is unchanged (posture-resolver).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { performSnowballSearch, resolveSeedPaperWithFallback, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { normalizeSeedInput } from '../src/seed-adapter.mjs';
import { dedupeSeedList, seedEntityId, mergeSnowballResults } from '../src/seed-identity.mjs';
import { runMixedInitiativeGate } from '../src/gate.mjs';
import { extractLedgerLean } from '../src/extraction.mjs';
import { runStage0Plan, stage0AllowsExecution, buildHeadlessApproval, PIPELINE_STATE_FILENAME } from '../src/stage0-plan.mjs';
import { advancePrismaWithSnowball, writePipelineState, readPipelineState } from '../src/pipeline-state.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';
import { runPostApproveBreadth } from '../src/breadthStage.mjs';
import { buildBreadthTelemetry } from '../src/breadthTelemetry.mjs';
import { reviewSeatLineage } from '../src/reviewSeatLabels.mjs';
import { applyLiteratureReviewTriageLock } from '../src/triage-lock-apply.mjs';
import { composeLiteratureReviewAdversarialPass } from '../src/adversarial-compose.mjs';

function parseArgs(argv) {
  // Track B7 W2 — distinct fields: snowballDepth (integer hops), triageBand (band),
  // adversarialRounds (N). CLI --depth is freestyle snowball hops only (never band).
  const o = {
    seeds: [], seedList: null, snowballDepth: 1, adversarialRounds: 1, maxPapers: 6, columns: ['method', 'evidence', 'result'], stakes: 'medium', out: 'litreview-out', mockUser: null, live: false,
    content: [], intent: null, planRunDir: null, planDecision: null, planEditedFile: null, planToken: null, planPolicyGrant: null,
    triageDepth: null, triageTier: null, triageBand: null,
    snowballDepthExplicit: false, adversarialRoundsExplicit: false, depthExplicit: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--seed') o.seeds.push(argv[++i]);
    else if (a === '--seed-list') o.seedList = argv[++i];
    else if (a === '--depth') {
      // Freestyle snowball hop budget only — never a process-depth band token.
      o.snowballDepth = parseInt(argv[++i], 10) || 1;
      o.snowballDepthExplicit = true;
      o.depthExplicit = true; // legacy alias flag for lock partial-override probes
    }
    else if (a === '--triage-depth') o.triageDepth = argv[++i];
    else if (a === '--triage-tier') o.triageTier = argv[++i];
    else if (a === '--max-papers') o.maxPapers = parseInt(argv[++i], 10) || 6;
    else if (a === '--columns') o.columns = String(argv[++i]).split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--stakes') o.stakes = argv[++i];
    else if (a === '--out') o.out = argv[++i];
    else if (a === '--mock-user') o.mockUser = argv[++i];
    else if (a.startsWith('--mock-user=')) o.mockUser = a.slice('--mock-user='.length);
    else if (a === '--live') o.live = true;
    else if (a === '--content') o.content.push(argv[++i]);
    else if (a === '--intent') o.intent = argv[++i];
    else if (a === '--plan-run-dir') o.planRunDir = argv[++i];
    else if (a === '--plan-decision') o.planDecision = String(argv[++i]).toUpperCase();
    else if (a === '--plan-edited-file') o.planEditedFile = argv[++i];
    else if (a === '--plan-token') o.planToken = argv[++i];
    else if (a === '--plan-policy-grant') o.planPolicyGrant = argv[++i];
    else if (a === 'ingest') o.seeds.push(argv[++i]);
  }
  return o;
}

// Stage-0 LLM adapters over the live seats: the ONE Gandalf summarize call, the ONE
// bounded derive call, and the ONE bounded re-derive parse (APPROVE-with-EDITs). All
// three are pass-throughs to the shared module's fenced payloads — the CLI adds no
// derivation logic of its own. With no live seats bound, the adapters stay undefined
// and Stage-0 fails/aborts honestly instead of fabricating a plan.
function buildStage0Adapters(agent) {
  if (!agent) return { summarize: undefined, derive: undefined, parse: undefined };
  const summarize = async (payload) =>
    agent(['[literature-review Stage-0 — Gandalf grounded summary]', payload.instructions, '', payload.fencedContent].join('\n'), {
      label: 'stage0-gandalf-summarize', role: 'synthesizer',
      schema: { type: 'object', required: ['sentences'], properties: { sentences: { type: 'array' } } },
    });
  const derive = async (payload) =>
    agent(['[literature-review Stage-0 — bounded plan derive]', payload.instructions, '', payload.fencedContext].join('\n'), {
      label: 'stage0-derive-plan', role: 'synthesizer', schema: { type: 'object' },
    });
  const parse = async ({ editedProse, groundedSources }) =>
    agent([
      '[literature-review Stage-0 — bounded re-derive of the APPROVEd edited plan prose]',
      'Emit ONLY a JSON PlanArtifact (artifactVersion "plan-artifact/1") re-derived from the',
      'edited prose below. Every plan element must carry verbatim anchors quoting the fenced',
      'grounded sources word-for-word; invent nothing absent from the prose or the sources.',
      '=== APPROVED EDITED PROSE ===', editedProse, '=== END PROSE ===',
      '=== GROUNDED SOURCES (verbatim anchor targets) ===', JSON.stringify(groundedSources, null, 2), '=== END SOURCES ===',
    ].join('\n'), {
      label: 'stage0-rederive', role: 'synthesizer', schema: { type: 'object' },
    });
  return { summarize, derive, parse };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));

  // ---- Wave 10: the canonical multi-seed list, FIRST. Strict validation (the shared
  // Wave-6 checkpoint) runs here at the boundary — a malformed identifier stops the
  // run before any child-process handoff — and list-level dedupe is deterministic:
  // exact identity-key duplicates collapse; id-less near-title pairs are kept
  // DISTINCT and flagged (never fuzzy-merged).
  const seedInput = await normalizeSeedInput({ seedSpecs: opts.seeds, seedListPath: opts.seedList });
  if (seedInput.rejected.length > 0) {
    console.error('Seed validation FAILED — nothing ran, nothing was handed off:');
    for (const r of seedInput.rejected) {
      console.error(`  ✗ ${typeof r.seed === 'string' ? r.seed : JSON.stringify(r.seed)}: ${r.reason}`);
    }
    process.exit(1);
  }
  const seedDedupe = await dedupeSeedList(seedInput.seeds);
  const canonicalSeeds = seedDedupe.seeds;
  for (const m of seedDedupe.merges) {
    console.log(`Seed dedupe: ${m.key} was supplied ${m.absorbedCount + 1}× — collapsed to one seed.`);
  }
  for (const c of seedDedupe.collisions) {
    console.log(`SEED COLLISION FLAG (kept DISTINCT — no fuzzy merge): "${c.leftTitle}" vs "${c.rightTitle}": ${c.reason}`);
  }

  const intentPresent = typeof opts.intent === 'string' && opts.intent.trim() !== '';
  const planPhase = opts.content.length > 0 || intentPresent || canonicalSeeds.length > 0;
  if (!planPhase) {
    console.error('Usage: node bin/cli.mjs [--seed spec]... [--seed-list json] [--depth N] [--max-papers N] [--columns a,b,c] [--stakes t] [--out dir] [--mock-user seq] [--live] [--content root]... [--intent text] [--plan-decision APPROVE|EDIT|ABORT] [--plan-edited-file p] [--plan-token t] [--plan-policy-grant id]');
    console.error('Seed specs: doi:<id>[|title] | pmid:<id>[|title] | arxiv:<id>[|title] | title:<title> | bare DOI/PMID/arXiv id.');
    process.exit(1);
  }
  const started = new Date().toISOString();
  const t0 = Date.now();
  fs.mkdirSync(opts.out, { recursive: true });

  // Track B7 W2 — dual-knob triage lock apply (Contract 1):
  // snowballDepth + adversarialRounds from the same locked knobs object; band only
  // as opts.triageBand / log band=; never store integer snowball in a band field.
  // Partial freestyle override while FOUNDRY_TRIAGE_DEPTH/--triage-depth present → refuse.
  const applied = applyLiteratureReviewTriageLock(opts, { env: process.env });
  if (applied.resolved) {
    console.log(
      `triage: band=${applied.resolved.band} snowballDepth=${opts.snowballDepth} adversarialRounds=${opts.adversarialRounds} source=${applied.resolved.source}`,
    );
  }

  // ---- 0a. Seed PRE-FLIGHT (2026-08-25, the journal-0004 fix, John-ratified card):
  // resolve every catalog-id CLI seed's metadata BEFORE binding paid live seats — the
  // cheapest feasibility check runs first, and its result is REUSED as the snowball
  // seed load (no second fragile network call). Title-hash seeds have no catalog
  // identity (pinned in seed-identity.mjs) and are never probed. If EVERY catalog-id
  // seed fails on BOTH providers, HALT here with a named reason — zero paid capacity
  // reserved (journal 0004: seats bound, Stage-0 ran, THEN the seed died).
  const seedPreflight = new Map();       // `${idType}:${id}` -> { paper, provider, fallbackReason? }
  const seedPreflightFailed = new Set(); // `${idType}:${id}` that failed BOTH providers
  // --mock-user marks a hermetic/test-ish invocation: probing would burn network and
  // exit 1 offline (2026-08-25 review fix) — skip with a stamp; the snowball stage's
  // own fallback still guards a real run that reaches it.
  const preflightSkipped = Boolean(opts.mockUser);
  if (preflightSkipped) {
    console.log('  ~ seed pre-flight SKIPPED (--mock-user run) — stamped; live runs always pre-flight.');
  } else {
    const probeSeeds = canonicalSeeds.filter((s) => seedEntityId(s) !== null);
    let preflightFailures = 0;
    for (const seed of probeSeeds) {
      try {
        const resolved = await resolveSeedPaperWithFallback(seedEntityId(seed));
        seedPreflight.set(`${seed.idType}:${seed.id}`, resolved);
        if (resolved.provider !== 's2') {
          console.log(`  ~ seed ${seed.idType}:${seed.id} pre-flight resolved via OpenAlex fallback (S2 unavailable) — stamped, never silent.`);
        }
      } catch (err) {
        preflightFailures += 1;
        seedPreflightFailed.add(`${seed.idType}:${seed.id}`);
        console.log(`  ! seed ${seed.idType}:${seed.id} pre-flight failed on BOTH providers: ${err.message}`);
      }
    }
    if (probeSeeds.length > 0 && preflightFailures === probeSeeds.length) {
      console.error('HALT before seat binding: every catalog-id seed failed pre-flight resolution (S2 + OpenAlex). No paid capacity was reserved. Check network / S2_API_KEY (env var; raises the S2 rate limit) and retry.');
      process.exit(1);
    }
  }

  // ---- live seats (or an honest absence of them) ----
  const LIVE = opts.live || process.env.LITREVIEW_LIVE === '1';
  let agent = null;
  if (LIVE) {
    const { buildLiveRoundAgent, makeReachedFamilyTracker } =
      await import('fil<path>');
    const tracker = makeReachedFamilyTracker();
    agent = await buildLiveRoundAgent({ tracker, env: process.env }); // prefs-aware seats
    console.log('LIVE seats bound from coding/review family prefs (reviewer/judge/debate → REVIEW_FAMILY, synthesizer → CODING_FAMILY).');
  }

  // ---- 0. Stage-0 PLAN phase (Wave 9): plan-first, gate HALT BEFORE snowball ----
  // The entire block runs before any deterministic pipeline stage. Snowball is
  // unlocked ONLY when stage0AllowsExecution() is true; every other Stage-0 outcome
  // (HALTED awaiting approval, gate ABORT, stamped re-derive abort, intake failure)
  // returns here without src/search.mjs ever being entered.
  let pipelineState = null;
  let planStatePath = null;
  let approvedSeeds = [];
  /** @type {ReturnType<typeof buildBreadthTelemetry>|null} */
  let breadthTelemetry = null;
  if (planPhase) {
    const planRunDir = opts.planRunDir || path.join(opts.out, 'plan-run');
    const { summarize, derive, parse } = buildStage0Adapters(agent);
    // A FRESH content/intent plan derivation needs the live summarize/derive seats; a
    // RESUME from a serialized HALT boundary needs none (APPROVE-verbatim spends zero
    // LLM calls, and an EDIT without a parse seat fail-to-ABORTs honestly inside
    // Stage-0). A SEEDS-ONLY run needs none either: the shared module's seeds-only
    // bootstrap route is deterministic (zero Gandalf calls, zero derive calls).
    if (!agent && (opts.content.length > 0 || intentPresent)) {
      let haltedState = null;
      try {
        haltedState = readPipelineState(path.join(planRunDir, PIPELINE_STATE_FILENAME));
      } catch {
        haltedState = null;
      }
      if (haltedState?.status !== 'HALTED') {
        console.log('\nSTOPPED HONESTLY: the Stage-0 PLAN phase needs live model seats to derive a plan');
        console.log('from content/intent (--live / LITREVIEW_LIVE=1) and no serialized HALTED plan');
        console.log(`exists to resume at ${planRunDir}. Nothing was derived; nothing was fabricated.`);
        writeRunRecord({ started, t0, opts, result: 'stage0 not run (no live seats, no halted state to resume)', crossModel: false });
        return;
      }
    }
    const gateOptions = { maxEdits: 1 };
    if (opts.planToken || opts.planPolicyGrant) {
      gateOptions.approvalProvider = await buildHeadlessApproval({
        runDir: planRunDir,
        token: opts.planToken || undefined,
        policyGrantIdentity: opts.planPolicyGrant || undefined,
      });
    } else if (opts.planDecision) {
      gateOptions.decision = opts.planDecision;
      if (opts.planEditedFile) gateOptions.editedProse = fs.readFileSync(opts.planEditedFile, 'utf8');
    }
    console.log('Stage-0 PLAN phase: research plan -> one-shot APPROVE/EDIT/ABORT gate (frozen researchPrime gate)...');
    const stage0 = await runStage0Plan({
      runDir: planRunDir,
      // Wave 10: the canonical (validated + deduped) multi-seed list rides through
      // Stage-0 into PlanArtifact.seeds — the ONE field snowball later consumes.
      intake: { roots: opts.content, intent: opts.intent, seeds: canonicalSeeds.map((s) => ({ ...s })) },
      summarize,
      grounding: { buildNormalizedView, groundQuote },
      derive,
      parse,
      gate: gateOptions,
      log: (m) => console.log(m),
    });
    if (!stage0AllowsExecution(stage0)) {
      console.log(`\nStage-0 ${stage0.status}: ${stage0.reason ?? 'awaiting plan approval'}`);
      if (stage0.status === 'HALTED') {
        console.log(`Plan artifact: ${stage0.planArtifactPath}`);
        console.log(`Pipeline state (resume boundary): ${stage0.statePath}`);
        console.log('Resume with the SAME command plus --plan-decision APPROVE|EDIT|ABORT');
        console.log('(EDIT needs --plan-edited-file <path>; headless: --plan-token / --plan-policy-grant).');
      }
      console.log('src/search.mjs (snowball) was NOT entered; nothing past the plan gate ran.');
      writeRunRecord({ started, t0, opts, result: `stage0-${stage0.status.toLowerCase()}: ${stage0.reason ?? 'awaiting approval'}`, crossModel: false });
      return;
    }
    pipelineState = stage0.state;
    planStatePath = stage0.statePath;
    console.log(`Stage-0 plan APPROVED (${stage0.decision.path}) — snowball unlocked.`);
    // Wave 10: snowball/PRISMA consume seeds ONLY from the APPROVED PlanArtifact's
    // seeds field — never from the CLI args, and never re-derived.
    approvedSeeds = Array.isArray(stage0.executionArtifact.seeds) ? stage0.executionArtifact.seeds : [];

    // Wave 2–3 — post-APPROVE breadth hook (parallel + merge/dedupe): facetsFromPlan
    // first, then optional parallel per-facet scoped gather over shared multi-seed S
    // (ConcurrencyManager-capped), merge+dedupe into one corpus, BEFORE the main
    // snowball/depth path below. Active only when status is APPROVED and
    // facets.length ≥ 1; empty facets stamp honestly and invent nothing.
    console.log('Breadth stage (post-APPROVE, parallel): facetsFromPlan before main snowball...');
    const breadthOutcome = await runPostApproveBreadth({
      planStatus: pipelineState.status,
      plan: stage0.executionArtifact,
      seeds: approvedSeeds,
      options: { depth: opts.snowballDepth },
      log: (m) => console.log(m),
    });
    // Wave 5: pure honesty projection for run telemetry / dual-suite inspection.
    breadthTelemetry = buildBreadthTelemetry({
      outcome: breadthOutcome,
      skill: 'literature-review',
    });
    try {
      const breadthSummary = {
        version: breadthOutcome.version,
        ran: breadthOutcome.ran,
        reason: breadthOutcome.reason,
        stamp: breadthOutcome.stamp,
        facetCount: breadthOutcome.facets.length,
        facetIds: breadthOutcome.facets.map((f) => f.id),
        sharedSeedCount: breadthOutcome.sharedSeeds.length,
        concurrency: breadthOutcome.concurrency,
        maxActive: breadthOutcome.maxActive,
        corpus: {
          uniqueCount: breadthOutcome.corpus?.uniqueCount ?? 0,
          totalHitsSeen: breadthOutcome.corpus?.totalHitsSeen ?? 0,
          merges: breadthOutcome.corpus?.merges ?? [],
          paperIds: (breadthOutcome.corpus?.entries ?? []).map((e) => e.paperId),
        },
        events: breadthOutcome.events,
        facetResults: breadthOutcome.facetResults.map((r) => ({
          facetId: r.facetId,
          order: r.order,
          hitCount: Array.isArray(r.hits) ? r.hits.length : 0,
          seedCount: r.seedCount,
          error: r.error,
        })),
        // Wave 5 honesty stamp block (also mirrored into journal/runs).
        breadthTelemetry,
      };
      fs.writeFileSync(
        path.join(opts.out, 'breadth-stage.json'),
        JSON.stringify(breadthSummary, null, 2),
        'utf8',
      );
    } catch {
      /* best-effort artifact */
    }

    if (approvedSeeds.length === 0) {
      console.log('The approved plan carries no seeds: the seed-driven snowball stage has nothing to expand.');
      writeRunRecord({
        started, t0, opts,
        result: 'stage0-approved (no seeds in plan; snowball skipped)',
        crossModel: false,
        breadthTelemetry,
      });
      return;
    }
  }

  // ---- 1.+2. multi-seed snowball + PRISMA (deterministic; venue ranks, never excludes
  //      by default). Per-seed results merge by EXACT paperId identity (deterministic
  //      cross-seed dedupe, no fuzzy merge) and PRISMA advances ONCE over the merge.
  //      Runs ONLY after the post-APPROVE breadth stage above has completed (or
  //      honestly skipped). ----
  const resolvableSeeds = [];
  for (const seed of approvedSeeds) {
    if (seedEntityId(seed) === null) {
      console.log(`  ~ seed ${seed.idType}:${seed.id} ("${seed.title}") has no external catalog identity — kept in the plan, skipped by snowball (no fuzzy resolution).`);
    } else if (seedPreflightFailed.has(`${seed.idType}:${seed.id}`)) {
      // 2026-08-25 review fix: a both-providers-dead seed used to be handed to snowball
      // anyway — refetch, throw, run dies AFTER seats bound + Stage-0 (the exact 0004
      // class, resurrected for any partial-fail mix). Skip it STAMPED instead.
      console.log(`  ! seed ${seed.idType}:${seed.id} SKIPPED by snowball — pre-flight failed on BOTH providers (stamped; the run proceeds on the surviving seeds).`);
    } else {
      resolvableSeeds.push(seed);
    }
  }
  let candidates = [];
  let seedChunks = [];
  if (resolvableSeeds.length > 0) {
    console.log(`Snowball search over ${resolvableSeeds.length} seed(s) (snowballDepth ${opts.snowballDepth})...`);
    const perSeedRuns = [];
    for (const seed of resolvableSeeds) {
      const entityId = seedEntityId(seed);
      const pf = seedPreflight.get(`${seed.idType}:${seed.id}`);
      const result = await performSnowballSearch(entityId, DEFAULT_VENUE_WHITELIST, {
        depth: opts.snowballDepth,
        // Reuse the pre-flight metadata (0a) — skips the fragile seed-load call entirely.
        seedPaper: pf?.paper,
        // 2026-08-25 review fix: a pre-flight OpenAlex fallback must land in the run's
        // providerFallbacks record too — "recorded, never silent" (journal 0005).
        seedPaperFallback: pf && pf.provider !== 's2'
          ? { from: 's2', to: pf.provider, reason: pf.fallbackReason || 'pre-flight fallback' }
          : null,
      });
      perSeedRuns.push({ seed, entityId, result });
    }
    const merged = mergeSnowballResults(perSeedRuns, DEFAULT_VENUE_WHITELIST);
    for (const m of merged.seedMerges) {
      console.log(`  seed dedupe: ${m.absorbed.join(', ')} resolve to the same paper as ${m.kept} (${m.paperId}) — merged deterministically by identity precedence.`);
    }
    fs.writeFileSync(path.join(opts.out, 'prisma-exclusions.json'), JSON.stringify(merged.prismaExclusions, null, 2), 'utf8');
    fs.writeFileSync(path.join(opts.out, 'citation-graph.mmd'), merged.mermaid || '');
    candidates = merged.candidates.slice(0, opts.maxPapers);
    seedChunks = merged.seedPapers.map((sp) => sp.paper?.abstract).filter(Boolean);
    console.log(`  included=${merged.candidates.length} · taking top ${candidates.length} · excluded(PRISMA)=${merged.prismaExclusions.exclusions.length}`);
    if (pipelineState) {
      // Stage-0 initialized PRISMA; snowball is the ONLY stage that advances it.
      pipelineState = advancePrismaWithSnowball(pipelineState, merged);
      writePipelineState(planStatePath, pipelineState);
    }
  }

  // ---- 3. mixed-initiative gate (TTY-aware; copilot honest about its seat) ----
  await runMixedInitiativeGate(candidates, seedChunks, {
    mockUser: opts.mockUser,
    agent: agent
      ? (prompt, o2 = {}) => agent(prompt, { ...o2, role: 'synthesizer', label: 'copilot' })
      : async (_p, o2 = {}) => `[copilot unavailable — no live seats bound; query "${o2?.query || ''}" not answered, nothing invented]`,
    log: (m) => console.log(m),
  });

  if (!agent) {
    console.log('\nSTOPPED HONESTLY: no live model seats bound (--live / LITREVIEW_LIVE=1).');
    console.log('Deterministic outputs above (ingest/snowball/PRISMA/graph) are real; claim');
    console.log('extraction and adversarial verification did NOT run. Nothing was fabricated.');
    writeRunRecord({
      started, t0, opts,
      result: 'deterministic-only (no live seats)',
      crossModel: false,
      breadthTelemetry,
    });
    return;
  }

  // ---- 4. LEAN extraction: 1 call/paper + deterministic quote grounding ----
  const allAssumptions = [];
  const allRejected = [];
  for (const cand of candidates) {
    const text = cand.abstract || '';
    if (!text.trim()) { console.log(`  ~ ${cand.title}: no text available — skipped (stamped)`); continue; }
    const { ledger, rejected } = await extractLedgerLean(cand, text, opts.columns, agent);
    allAssumptions.push(...ledger.assumptions);
    allRejected.push(...rejected);
    console.log(`  ✓ ${String(cand.title).slice(0, 60)}: ${ledger.assumptions.length} grounded claim(s), ${rejected.length} rejected (fabricated quote)`);
  }

  // ---- 5. weighted consensus synthesis (deterministic math) ----
  const { runFinalSynthesis } = await import('../src/synthesis.mjs');
  const withLedgers = candidates
    .map((c) => ({ ...c, ledger: { assumptions: allAssumptions.filter((a) => a.source.entityId === c.paperId) } }))
    .filter((c) => c.ledger.assumptions.length);
  let synth = null;
  if (withLedgers.length) {
    synth = await runFinalSynthesis(withLedgers, opts.columns, {
      ledgerJsonPath: path.join(opts.out, 'assumptions-ledger.json'),
      ledgerMarkdownPath: path.join(opts.out, 'assumptions-ledger.md'),
      matrixJsonPath: path.join(opts.out, 'parameterized-matrix.json'),
    });
    console.log(`Synthesis: ${synth.ledger.assumptions.length} assumption(s), ${synth.matrix.rows.length} matrix row(s) → ${opts.out}/`);
  } else {
    console.log('Synthesis SKIPPED (honest): zero grounded assumptions extracted.');
  }

  // ---- 6. Final adversarial stage — sole entry: composeLiteratureReviewAdversarialPass
  //      (N = knobs.adversarialRounds invocations; each = RP intake + runGovernedRound; never runEngine) ----
  let adversarial = null;
  if (synth) {
    const ledgerText = fs.readFileSync(path.join(opts.out, 'assumptions-ledger.md'), 'utf8');
    const northStar = `An honest, source-grounded synthesis of the literature around the seed paper, compared on: ${opts.columns.join(', ')}`;
    const roles = ['Skeptic', 'Contrarian', 'Analyst'];
    const band = opts.triageBand || opts._triageKnobs?.depth || null;
    const knobs = {
      snowballDepth: opts.snowballDepth,
      adversarialRounds: opts.adversarialRounds,
      depth: band,
    };
    adversarial = await composeLiteratureReviewAdversarialPass({
      ledger: synth.ledger,
      band,
      knobs,
      agent,
      stakes: opts.stakes,
      northStar,
      researchPrimeIntake: {
        intent: northStar,
        depth: band || undefined,
        scope: 'medium',
      },
      collectReviews: async ({ agent: ag, round }) => {
        return Promise.all(roles.map(async (role, i) => {
          const out = await ag([
            `[literature-review final adversarial pass — ${role} · invoke ${round}] Attack this synthesized assumptions ledger.`,
            `For every defect: claim_id = the EXACT id of the ledger assumption you dispute (agreement is keyed on it),`,
            `topic, severity (BLOCKER|MAJOR|MINOR|NIT), traces_to_north_star yes/no, message.`,
            `NORTH STAR: ${northStar}`,
            `=== LEDGER ===\n${ledgerText}\n=== END ===`,
          ].join('\n'), {
            label: `litreview-reviewer:${role}:r${round}`, role: 'reviewer',
            schema: { type: 'object', required: ['findings'], properties: { findings: { type: 'array' } } },
          });
          // Wave 5: gemini-cli lineage labels only — never API-style Gemini product ids.
          return {
            reviewer: role,
            lineage: reviewSeatLineage(i),
            findings: Array.isArray(out?.findings) ? out.findings : [],
          };
        }));
      },
    });
    if (adversarial.skipped) {
      console.log(`Adversarial compose SKIPPED (honest): adversarialRounds=${opts.adversarialRounds} → invokeCount=0`);
    } else {
      const last = adversarial.rounds[adversarial.rounds.length - 1];
      const lastLabel =
        last?.tally?.verdict ?? (last?.skipped ? 'skipped-round' : 'n/a');
      console.log(
        `Adversarial compose: invokeCount=${adversarial.invokeCount} (N=${opts.adversarialRounds}) · ` +
          `last=${lastLabel} · ${last?.tally?.blockers?.length ?? 0} agreed blocker(s)`,
      );
    }
    fs.writeFileSync(path.join(opts.out, 'adversarial-round.json'), JSON.stringify({
      stamp: adversarial.skipped
        ? 'adversarial compose skipped — adversarialRounds<=0; extraction floors remain full-strength'
        : `composeLiteratureReviewAdversarialPass invokeCount=${adversarial.invokeCount} — N× (RP intake + runGovernedRound); NOT runEngine`,
      skipped: adversarial.skipped,
      invokeCount: adversarial.invokeCount,
      intakeStamps: adversarial.intakeStamps,
      rounds: adversarial.rounds.map((r) => ({
        verdict: r?.tally?.verdict,
        blockers: r?.tally?.blockers,
        judge: r?.judgeVerdict,
        skipped: r?.skipped,
      })),
      floor: {
        requireQuoteGrounding: adversarial.floor?.requireQuoteGrounding,
        oneCallPerPaperExtraction: adversarial.floor?.oneCallPerPaperExtraction,
        minGroundedClaimsPerPaper: adversarial.floor?.minGroundedClaimsPerPaper,
      },
      rejectedFabricatedQuotes: allRejected,
      reviewSeatLabels: roles.map((_, i) => reviewSeatLineage(i)),
    }, null, 2));
  }

  const lastVerdict = adversarial?.rounds?.[adversarial.rounds.length - 1];
  writeRunRecord({
    started, t0, opts,
    result: synth
      ? `synthesized ${synth.ledger.assumptions.length} assumptions; adversarial invokeCount=${adversarial?.invokeCount ?? 0} skipped=${!!adversarial?.skipped}; last=${lastVerdict?.tally?.verdict ?? 'n/a'}; rejected-fabricated=${allRejected.length}`
      : 'no grounded assumptions',
    crossModel: true,
    breadthTelemetry,
  });
}

function writeRunRecord({ started, t0, opts, result, crossModel, breadthTelemetry = null }) {
  try {
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = path.join(skillDir, 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({
        skill: 'literature-review', tier: crossModel ? 'live-cross-family' : 'deterministic-only',
        started, ended: new Date().toISOString(),
        input: opts.seeds.length ? opts.seeds.join(' ; ') : null,
        params: {
          snowballDepth: opts.snowballDepth,
          adversarialRounds: opts.adversarialRounds,
          triageBand: opts.triageBand ?? null,
          maxPapers: opts.maxPapers,
          columns: opts.columns,
          stakes: opts.stakes,
          seedList: opts.seedList,
        },
        output: opts.out, result, cross_model: crossModel,
        // Wave 5: family / gemini-cli labels only — no API-style Gemini product ids.
        models: {
          review: 'gemini-cli',
          review_family: 'REVIEW_FAMILY',
          coding_family: 'CODING_FAMILY',
        },
        // Wave 5: breadth honesty stamps (from-branches / none / facet errors).
        breadthTelemetry: breadthTelemetry ?? null,
        duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
      }, null, 2) + '\n');
  } catch { /* best-effort */ }
}

main().catch((err) => {
  console.error(`CLI execution failed: ${err.message}`);
  process.exit(1);
});

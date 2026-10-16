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
//   - live model seats via researchPrime's live-round-agent (review roles →
//     REVIEW_FAMILY, extraction/synthesizer/copilot → CODING_FAMILY). No live seats bound ⇒
//     the run STOPS after the deterministic stages with an explicit stamp. Nothing
//     is ever fabricated.
//
// Usage:
//   node bin/cli.mjs [--seed <spec>]... [--seed-list <json-file>] [--depth N]
//        [--max-papers N] [--relevance-floor F] [--corpus-relevance-min F]
//        [--columns a,b,c] [--stakes low|medium|high] [--out <dir>]
//        [--mock-user "q: ...|approve"] [--live]
//        [--content <root>]... [--intent "<research intent>"] [--plan-run-dir <dir>]
//        [--plan-decision APPROVE|EDIT|ABORT] [--plan-edited-file <path>]
//        [--plan-token <token>] [--plan-policy-grant <identity>]
//   Seed specs (Wave 10 — replacing the single --seed <pdf-url>): doi:<id>[|title],
//   pmid:<id>[|title], arxiv:<id>[|title], title:<title>, a doi.org / arxiv.org/abs
//   identifier URL, or a bare DOI/PMID/arXiv id; anything else is a title-only seed.
//   LITREVIEW_LIVE=1 (or --live): bind the saved coding/review families; a verification
//   seat without served-model attestation HALTs honestly.
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
import { advancePrismaWithSnowball, recordExtractionNoText, writePipelineState, readPipelineState } from '../src/pipeline-state.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';
import { runPostApproveBreadth } from '../src/breadthStage.mjs';
import { buildBreadthTelemetry } from '../src/breadthTelemetry.mjs';
import { reviewSeatLineageFromReceipt } from '../src/reviewSeatLabels.mjs';
import { makeSeatTelemetry, wrapAgentWithSeatTelemetry, seatRecordFields } from '../src/seatTelemetry.mjs';
import { applyLiteratureReviewTriageLock } from '../src/triage-lock-apply.mjs';
import { assembleCandidatesWithSeeds, truncateCandidatesPreservingSeeds, truncationPrismaExclusions, buildSeedPrismaInclusions } from '../src/candidate-assembly.mjs';
import { SOURCING_CHAIN, acquireTextWithProvenance, stampTextProvenance, makeOpenAlexAbstractResolver, preScreenSourcing } from '../src/text-sourcing.mjs';
import { applyRelevanceScreening } from '../src/relevance.mjs';
import { buildRunSummary, finalizeRunSummary, formatConsoleSummary, formatRunResult, VERDICT_CORPUS_OFF_TOPIC } from '../src/run-summary.mjs';
import { resolveRunConfig, parseMaxPapers, combineInspectableExclusions } from '../src/run-config.mjs';
import { composeLiteratureReviewAdversarialPass } from '../src/adversarial-compose.mjs';

function parseArgs(argv) {
  // Track B7 W2 — distinct fields: snowballDepth (integer hops), triageBand (band),
  // adversarialRounds (N). CLI --depth is freestyle snowball hops only (never band).
  const o = {
    seeds: [], seedList: null, snowballDepth: 1, adversarialRounds: 1, maxPapers: 6, relevanceFloor: null, corpusRelevanceMin: null, columns: ['method', 'evidence', 'result'], stakes: 'medium', out: 'litreview-out', mockUser: null, live: false,
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
    else if (a === '--max-papers') o.maxPapers = parseMaxPapers(argv[++i]);
    // Wave 3/5: the configurable hard relevance floor. NaN is passed through so
    // resolveRunConfig REFUSES it outright at the boundary (an unnamed bound cannot
    // be tested).
    else if (a === '--relevance-floor') o.relevanceFloor = Number(argv[++i]);
    // Wave 4/5: the configurable corpus-relevance honesty minimum — same NaN
    // pass-through refusal contract as the floor.
    else if (a === '--corpus-relevance-min') o.corpusRelevanceMin = Number(argv[++i]);
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

  // Wave 5 (journal 0010): resolve the relevance/honesty knobs ONCE at the boundary —
  // source-level defaults, named [0,1] bounds, out-of-bounds REFUSED here before any
  // work runs; seed exemption and inspectable exclusions hold by construction.
  const runConfig = resolveRunConfig({
    relevanceFloor: opts.relevanceFloor,
    corpusRelevanceMin: opts.corpusRelevanceMin,
  });

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
    console.error('Usage: node bin/cli.mjs [--seed spec]... [--seed-list json] [--depth N] [--max-papers N] [--relevance-floor F] [--corpus-relevance-min F] [--columns a,b,c] [--stakes t] [--out dir] [--mock-user seq] [--live] [--content root]... [--intent text] [--plan-decision APPROVE|EDIT|ABORT] [--plan-edited-file p] [--plan-token t] [--plan-policy-grant id]');
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
  const seatTelemetry = makeSeatTelemetry();
  if (LIVE) {
    const { buildLiveRoundAgent, makeReachedFamilyTracker } =
      await import(new URL('../../../../trio/researchPrime/bin/live-round-agent.mjs', import.meta.url));
    const tracker = makeReachedFamilyTracker();
    const routed = await buildLiveRoundAgent({ tracker, env: process.env }); // prefs-aware seats
    agent = wrapAgentWithSeatTelemetry(routed, seatTelemetry);
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
  // Wave 4: the floor/floor-activity pair the run summary stamps — set by the Wave-3
  // screening when snowball runs; on the no-snowball path the floor was never active.
  let relevanceScreeningInfo = { relevance_floor: runConfig.relevance_floor, floor_active: false };
  // The sourcing chain (Wave 2): provider abstract → OpenAlex abstract → …; defined here
  // because (2026-09-05, Grok review F1) it now ALSO runs before relevance ranking.
  const sourcingChain = { 'openalex-abstract': makeOpenAlexAbstractResolver() };
  let prismaExclusions = { exclusions: [] };
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
    // Wave 1 (journal 0010 — Seeds always in): EVERY approved seed becomes a
    // canonical, relevance-exempt candidate BEFORE rank truncation, upserted by
    // stable identity (resolved catalog paperId, else its idType:id key) — never
    // duplicated, never rank-truncated. The 0010 run lost 10 of 12 seeds at the
    // old `slice(0, maxPapers)` on this exact line.
    const assembly = assembleCandidatesWithSeeds({
      candidates: merged.candidates,
      seeds: approvedSeeds,
      seedPapers: merged.seedPapers,
      seedMerges: merged.seedMerges,
    });
    // Wave 3 (journal 0010 — relevance-ranked, off-topic excluded): candidate order
    // becomes TF-IDF relevance to the seeds combined with normalized citation weight,
    // and below-floor non-seeds are EXCLUDED here — before truncation, extraction and
    // synthesis input — each a PRISMA `off-topic` exclusion stamped with its score,
    // the floor and its nearest seed. Seeds are exempt by construction; with no
    // scoreable seeds the floor is inactive and citation order is preserved. The 0010
    // run ranked by citations alone on this line and extracted Fiji over the topic.
    // (2026-09-05, Grok review F1) TEXT BEFORE RELEVANCE: a candidate the provider returned
    // without an abstract (Semantic Scholar often does) is sourced through the chain NOW,
    // so TF-IDF scores its real text and a record with none is named no-text — never
    // scored on its title and excluded as off-topic.
    const preScreen = await preScreenSourcing(assembly.candidates, { sources: sourcingChain });
    if (preScreen.attempted) {
      console.log(`  text before ranking: ${preScreen.sourced} of ${preScreen.attempted} abstract-less candidate(s) sourced through the chain`);
    }
    const screening = applyRelevanceScreening(preScreen.candidates, {
      relevanceFloor: runConfig.relevance_floor,
    });
    relevanceScreeningInfo = { relevance_floor: screening.relevance_floor, floor_active: screening.floor_active };
    // (2026-09-04, Gandalf read) truncation is an exclusion too: the budget's drops
    // become PRISMA `rank-truncated` rows, so the record and the flow agree.
    const truncation = truncateCandidatesPreservingSeeds(screening.retained, opts.maxPapers);
    // Wave 5: ONE inspectable, schema-validated exclusion record — snowball's own
    // exclusions, the screening's off-topic / no-text exclusions and the budget's
    // rank-truncated drops, combined in run order.
    prismaExclusions = combineInspectableExclusions(
      merged.prismaExclusions, screening.prismaExclusions,
      truncationPrismaExclusions(truncation.dropped, { maxPapers: opts.maxPapers, seedCount: truncation.seedCount }));
    const seedInclusions = buildSeedPrismaInclusions(screening.candidates);
    fs.writeFileSync(path.join(opts.out, 'prisma-exclusions.json'), JSON.stringify(prismaExclusions, null, 2), 'utf8');
    fs.writeFileSync(path.join(opts.out, 'prisma-inclusions.json'), JSON.stringify(seedInclusions, null, 2), 'utf8');
    fs.writeFileSync(path.join(opts.out, 'citation-graph.mmd'), merged.mermaid || '');
    fs.writeFileSync(path.join(opts.out, 'relevance-ranking.json'), JSON.stringify({
      stamp: 'per-candidate relevance ranking (TF-IDF cosine to seeds + normalized citation weight; floor screens non-seeds before extraction)',
      relevance_floor: screening.relevance_floor,
      floor_active: screening.floor_active,
      candidates: screening.candidates.map((c) => ({
        paperId: c.canonical_id ?? c.paperId ?? null,
        title: c.title ?? 'Untitled',
        is_seed: c.is_seed === true,
        relevance_score: c.relevance_score,
        nearest_seed: c.nearest_seed,
        citation_weight: c.citation_weight,
        combined_score: c.combined_score,
      })),
    }, null, 2), 'utf8');
    if (screening.excluded.length) {
      for (const ex of screening.prismaExclusions.exclusions) {
        console.log(`  - ${ex.reason} (PRISMA): "${String(ex.title).slice(0, 60)}" relevance ${ex.relevance_score} < floor ${ex.relevance_floor}`);
      }
    }
    candidates = truncation.kept;
    seedChunks = merged.seedPapers.map((sp) => sp.paper?.abstract).filter(Boolean);
    // (2026-09-05, Grok review F2) ONE identity on every surface: included = the kept set.
    console.log(`  included=${truncation.kept.length} of ${assembly.candidates.length} identified (retained ${screening.retained.length} at relevance floor ${screening.relevance_floor}${screening.floor_active ? '' : ' — inactive, no scoreable seeds'}; ${screening.excluded.length} screened out; ${truncation.dropped.length} rank-truncated; all ${truncation.seedCount} seed(s) kept) · excluded(PRISMA)=${prismaExclusions.exclusions.length}`);
    if (pipelineState) {
      // Stage-0 initialized PRISMA; snowball is the ONLY stage that advances it —
      // over the RETAINED candidate list (every seed included by construction), with
      // off-topic screening exclusions counted alongside the snowball's own.
      pipelineState = advancePrismaWithSnowball(pipelineState, {
        candidates: truncation.kept,
        prismaExclusions,
      });
      writePipelineState(planStatePath, pipelineState);
    }
  } else if (approvedSeeds.length > 0) {
    // (2026-09-05, Grok review F4) no catalog-resolvable seed (title-hash-only plans):
    // the user's seeds are STILL the corpus — assembled, stamped, in the PRISMA flow.
    const assembly = assembleCandidatesWithSeeds({ candidates: [], seeds: approvedSeeds });
    candidates = assembly.candidates;
    const seedInclusions = buildSeedPrismaInclusions(assembly.candidates);
    fs.writeFileSync(path.join(opts.out, 'prisma-inclusions.json'), JSON.stringify(seedInclusions, null, 2), 'utf8');
    console.log(`  no catalog-resolvable seed: ${candidates.length} user seed(s) assembled as the corpus (no snowball, no ranking)`);
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
  // Wave 4: the papers that were actually EXTRACTED (text sourced AND grounded claims
  // produced) — the only ones corpus_relevance is computed over.
  const extractedRecords = [];
  // Papers that failed the per-paper floor (zero grounded claims after quote-grounding) are
  // SKIPPED AND STAMPED here, never allowed to abort the run (journal 0008: one such paper
  // killed a run after eight papers were extracted and no ledger was written). The per-paper
  // function keeps its fail-closed contract (it still throws; B7-C3 canary); the run keeps going.
  const skippedPapers = [];
  // Wave 2 (journal 0010 — provenance-bearing text acquisition): seeds and ordinary
  // retained candidates take the SAME bounded sourcing chain (provider abstract →
  // OpenAlex abstract → Crossref abstract → arXiv/PMC full text → user PDF); the
  // winning link — or `none` with every applicable attempt — is stamped on the
  // record. The 0010 run skipped ten of twelve seeds at the old `cand.abstract || ''`
  // on this line while OpenAlex had their abstracts.
  // (2026-09-05, Grok review F3) a paper that yields NO text here leaves PRISMA `included`
  // as a `no-text` exclusion — never a silent console line.
  const noTextAtExtraction = [];
  for (let i = 0; i < candidates.length; i++) {
    const before = candidates[i];
    // text already sourced before ranking (F1) is reused with its stamp; otherwise the chain runs
    const preSourced = typeof before.text_source === 'string' && before.text_source !== 'none'
      && typeof before.abstract === 'string' && before.abstract.trim() !== '';
    const acquisition = preSourced
      ? { text: before.abstract, text_source: before.text_source, attempts: before.text_source_attempts }
      : await acquireTextWithProvenance(before, { sources: sourcingChain });
    const cand = candidates[i] = stampTextProvenance(before, acquisition);
    const text = acquisition.text || '';
    if (!text.trim()) {
      const attempted = cand.text_source_attempts.filter((a) => a.status !== 'skipped');
      console.log(`  ~ ${cand.title}: no text from any applicable source — text_source=none (${attempted.map((a) => `${a.source}:${a.status}`).join(', ')}); excluded as no-text (PRISMA)`);
      noTextAtExtraction.push({
        paperId: String(cand.canonical_id ?? cand.paperId ?? 'unknown'),
        title: typeof cand.title === 'string' ? cand.title : 'Untitled',
        reason: 'no-text',
        details: `no text from any applicable source at extraction (${attempted.map((a) => `${a.source}:${a.status}`).join(', ') || 'no link attempted'})`,
      });
      continue;
    }
    if (cand.text_source !== 'provider-abstract') {
      console.log(`  · ${String(cand.title).slice(0, 60)}: text sourced via ${cand.text_source} (chain fallback, stamped)`);
    }
    let extracted;
    try {
      extracted = await extractLedgerLean(cand, text, opts.columns, agent);
    } catch (err) {
      if (err && err.code === 'LIT_REVIEW_MIN_GROUNDED_CLAIMS') {
        const rejectedHere = Array.isArray(err.rejected) ? err.rejected : [];
        allRejected.push(...rejectedHere);
        skippedPapers.push({
          paperId: cand.paperId || '',
          title: cand.title || 'Untitled',
          reason: `below LIT_REVIEW_SAFETY_FLOOR.minGroundedClaimsPerPaper (${err.grounded ?? 0} grounded < ${err.minGrounded ?? '?'}); ${rejectedHere.length} fabricated quote(s) rejected`,
        });
        console.log(`  ~ ${String(cand.title).slice(0, 60)}: 0 grounded claim(s) after quote-grounding — paper skipped (stamped), run continues`);
        continue;
      }
      throw err;
    }
    const { ledger, rejected } = extracted;
    allAssumptions.push(...ledger.assumptions);
    allRejected.push(...rejected);
    extractedRecords.push(cand);
    console.log(`  ✓ ${String(cand.title).slice(0, 60)}: ${ledger.assumptions.length} grounded claim(s), ${rejected.length} rejected (fabricated quote)`);
  }
  if (skippedPapers.length) {
    fs.writeFileSync(path.join(opts.out, 'skipped-papers.json'), JSON.stringify({
      stamp: 'papers skipped at extraction: zero grounded claims after quote-grounding (per-paper floor held; run continued)',
      skipped: skippedPapers,
    }, null, 2));
    console.log(`  ${skippedPapers.length} paper(s) skipped at the floor — recorded in ${opts.out}/skipped-papers.json`);
  }
  if (noTextAtExtraction.length) {
    prismaExclusions = combineInspectableExclusions(prismaExclusions, { exclusions: noTextAtExtraction });
    fs.writeFileSync(path.join(opts.out, 'prisma-exclusions.json'), JSON.stringify(prismaExclusions, null, 2), 'utf8');
    if (pipelineState) {
      pipelineState = recordExtractionNoText(pipelineState, noTextAtExtraction);
      writePipelineState(planStatePath, pipelineState);
    }
    console.log(`  ${noTextAtExtraction.length} paper(s) excluded as no-text at extraction — PRISMA updated (${opts.out}/prisma-exclusions.json)`);
  }
  if (candidates.length) {
    // The auditable record of every attempted source — winning link or `none`,
    // one ordered attempt trail per retained candidate, seed and non-seed alike.
    fs.writeFileSync(path.join(opts.out, 'text-sourcing.json'), JSON.stringify({
      stamp: 'per-candidate sourcing-chain outcomes (provenance-bearing text acquisition; same shape for seeds and non-seeds)',
      chain: [...SOURCING_CHAIN],
      candidates: candidates.map((c) => ({
        paperId: c.canonical_id ?? c.paperId ?? null,
        title: c.title ?? 'Untitled',
        is_seed: c.is_seed === true,
        text_source: c.text_source ?? null,
        attempts: c.text_source_attempts ?? [],
      })),
    }, null, 2));
  }

  // ---- 4b. Wave 4 (journal 0010 — corpus-relevance stamp + honesty gate): ONE
  // authoritative run summary derived from the EXTRACTED corpus only. Below the
  // configurable corpus_relevance_min the verdict is corpus:off-topic and the ledger
  // is still written — stamped PARTIAL; the run can no longer report success on
  // extracted/grounded/synthesized counts alone. Console, ledger header and the
  // machine-readable run record all consume THIS object. ----
  let runSummary = buildRunSummary({
    extractedCandidates: extractedRecords,
    relevanceFloor: relevanceScreeningInfo.relevance_floor,
    floorActive: relevanceScreeningInfo.floor_active,
    corpusRelevanceMin: runConfig.corpus_relevance_min,
  });

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
      runSummary,
    });
    if (runSummary.verdict === VERDICT_CORPUS_OFF_TOPIC) {
      console.log(`Synthesis output written as PARTIAL (${VERDICT_CORPUS_OFF_TOPIC}): ${synth.ledger.assumptions.length} assumption(s) recorded → ${opts.out}/ — NOT a synthesis success.`);
    } else {
      console.log(`Synthesis: ${synth.ledger.assumptions.length} assumption(s), ${synth.matrix.rows.length} matrix row(s) → ${opts.out}/`);
    }
  } else {
    console.log('Synthesis SKIPPED (honest): zero grounded assumptions extracted.');
  }

  // ---- 6. Final adversarial stage — sole entry: composeLiteratureReviewAdversarialPass
  //      (N = knobs.adversarialRounds invocations; each = RP intake + runGovernedRound; never runEngine) ----
  let adversarial = null;
  const reviewSeatLabels = [];
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
          const label = `litreview-reviewer:${role}:r${round}`;
          const out = await ag([
            `[literature-review final adversarial pass — ${role} · invoke ${round}] Attack this synthesized assumptions ledger.`,
            `For every defect: claim_id = the EXACT id of the ledger assumption you dispute (agreement is keyed on it),`,
            `topic, severity (BLOCKER|MAJOR|MINOR|NIT), traces_to_north_star yes/no, message.`,
            `NORTH STAR: ${northStar}`,
            `=== LEDGER ===\n${ledgerText}\n=== END ===`,
          ].join('\n'), {
            label, role: 'reviewer',
            schema: { type: 'object', required: ['findings'], properties: { findings: { type: 'array' } } },
          });
          const receipt = seatTelemetry.receiptForLabel(label);
          const lineage = reviewSeatLineageFromReceipt(i, receipt);
          reviewSeatLabels.push(lineage);
          return {
            reviewer: role,
            lineage,
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
      reviewSeatLabels: [...new Set(reviewSeatLabels)],
    }, null, 2));
  }

  const lastVerdict = adversarial?.rounds?.[adversarial.rounds.length - 1];
  // Wave 4: the governed verdict fills the summary ONLY when the corpus verdict has
  // not already claimed it (corpus:off-topic is authoritative and never overridden);
  // console and run record then consume the same finalized object as the ledger did.
  runSummary = finalizeRunSummary(runSummary, { governedVerdict: lastVerdict?.tally?.verdict ?? null });
  for (const line of formatConsoleSummary(runSummary)) console.log(line);
  writeRunRecord({
    started, t0, opts,
    result: formatRunResult(
      runSummary,
      synth
        ? `synthesized ${synth.ledger.assumptions.length} assumptions; adversarial invokeCount=${adversarial?.invokeCount ?? 0} skipped=${!!adversarial?.skipped}; last=${lastVerdict?.tally?.verdict ?? 'n/a'}; rejected-fabricated=${allRejected.length}`
        : 'no grounded assumptions',
    ),
    seatTelemetry,
    breadthTelemetry,
    runSummary,
  });
}

function writeRunRecord({ started, t0, opts, result, crossModel = false, seatTelemetry = null, breadthTelemetry = null, runSummary = null }) {
  try {
    const seatFields = seatTelemetry
      ? seatRecordFields(seatTelemetry)
      : { cross_model: Boolean(crossModel), seat_families: [], models: [], tier: crossModel ? 'live-cross-family' : 'deterministic-only' };
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = path.join(skillDir, 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({
        skill: 'literature-review', tier: seatFields.tier,
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
        output: opts.out, result, cross_model: seatFields.cross_model,
        seat_families: seatFields.seat_families,
        models: seatFields.models,
        // Wave 5: breadth honesty stamps (from-branches / none / facet errors).
        breadthTelemetry: breadthTelemetry ?? null,
        // Wave 4 (journal 0010): THE corpus-relevance summary — the same object the
        // console lines and the ledger header rendered; null before extraction runs.
        run_summary: runSummary ?? null,
        duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
      }, null, 2) + '\n');
  } catch (error) {
    console.error(`literature-review run record failed: ${error.message}`);
  }
}

main().catch((err) => {
  console.error(`CLI execution failed: ${err.message}`);
  process.exit(1);
});

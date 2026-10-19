/**
 * Crucible Stage 2 launcher — Anchor steward campaign orchestration.
 * APPROVED Master Plan: MASTER-PLAN-v2.md (John Stage-1 stamp 2026-07-31).
 * North Star: NORTH-STAR.md v4 LOCKED 2026-07-31.
 *
 * Launch DETACHED via schtasks (background jobs died silently 9+ times).
 *   CRUCIBLE_AGENT_LIVE=1 node bin/_steward_stage2.mjs
 */
import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage2 } from './stage2.mjs';

const OUT = '<path>';
const NS_PATH = OUT + '/NORTH-STAR.md';
const PLAN_PATH = OUT + '/MASTER-PLAN-v2.md';
const APPROVAL_PATH = OUT + '/STAGE1-APPROVAL.md';

// Full docs on disk — decompose prompt budget-truncates embeds; paths let agents re-read.
const northStarDoc = readFileSync(NS_PATH, 'utf8');
const masterPlanDoc = readFileSync(PLAN_PATH, 'utf8');
const approvalDoc = readFileSync(APPROVAL_PATH, 'utf8');

const northStar =
  'NORTH STAR v4 LOCKED 2026-07-31 by John (full file: ' + NS_PATH + ').\n\n' +
  northStarDoc;

const masterPlan =
  'STAGE-1 APPROVED 2026-07-31 by John (full file: ' + PLAN_PATH + ').\n' +
  'Approval record:\n' + approvalDoc + '\n\n' +
  '=== MASTER PLAN v2 (APPROVED — decompose THIS) ===\n' +
  masterPlanDoc;

// NS v4 success criteria (13) — verbatim intent for inclusion test / Shark food.
const criteria = [
  '1. Spoken description → PROPOSED multi-stage scaffolding (coarse steps + Oranges annotations), batch-confirmed; zero chat turns persisted.',
  '2. Scaffolding authoring LIGHTWEIGHT: one confirmed session ENVELOPE covers compiles AND orchestrator-loop reflections (each shown; exhaustion hard-stops). No per-sentence confirmation dialog.',
  '3. Commission proposed FOR a named stage showing skill + seat + depth before spend; nothing runs until John confirms; confirmation records who.',
  '4. On validated handback: REFLECTION RECEIPT with Oranges prompts + PROPOSE next stage through propose→confirm. Unattended handback: queue reflection; compile at next session open (no unattended spend — Stage-1 Decision 1).',
  '5. PROGRESSIVE ELABORATION: starting a stage triggers targeted questions or offered researchPrime commission — never demanded at scaffold time.',
  '6. One campaign exercises AT LEAST TWO different commissioned skills.',
  '7. Stage artifacts render reviewably; spoken correction → new version through propose→confirm.',
  '8. Roadmap status reflects ACTUAL session state across park, restart, kill.',
  '9. All of it passes with AUTH ON, asserted on outcomes rather than plumbing.',
  '10. roadmap_events has exactly ONE writer, proven by a concurrency test.',
  '11. CONTINUITY: full restart with every context gone → first message states campaign state from ledger only; no re-ask; dead run + missing handback NAMED.',
  '12. ALTITUDE CONTRACT: typed attention projection (working|needs_you|deliverable_ready|blocked|idle) from one pure read-only function; High Seat fold write_authority none; badge within one poll; zero ambient beyond badge.',
  '13. PORTFOLIO AT A GLANCE from EXISTING portfolio index (no root walk); unreadable → unknown row, never silently shorter list. Consume index — do NOT re-plan/rebuild (A5 Wave-1 audit; Stage-1 Decision 2).',
  'GATE DECISIONS: (1) unattended reflections queue; (2) A5 audit not re-plan; (3) briefCacheStale FIXED in Wave 1 / Phase 1 under named-fix diff fence.',
  'NON-GOALS: no portfolio-index rebuild; no High Seat WRITE; no Crucible/Foreman/researchPrime internals; no adversarial review in product loop; no unattended spend; refuted e-1/e-4 stay dead.',
  'BUILD-vs-WIRE: Ecgberht propose/confirm/bind, packet-view, receipt-validate, brief.assembleBriefPacket, high-seat, rank, engine/portfolio/* are BUILT — wire/audit/fix. MISSING: Anchor commission executor (.py), dialogue→step_create, attention emitters, deliverable_ready state, chamber UI steps/proposal/confirm/artifact.',
  'HARDENING: every asserted property emits a mechanical gate; every surface wave has a failure-state table with unknown≠empty; durability = named atomic write + lock + concurrency test that fails if either is removed.',
];

mkdirSync(OUT + '/stage2-artifacts', { recursive: true });
mkdirSync(OUT + '/handoff', { recursive: true });

console.log('[steward-stage2] building live cross-family agent from coding/review family prefs...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[steward-stage2] agent built; routes=', JSON.stringify(routes));
console.log('[steward-stage2] starting runStage2 (FULL depth) on APPROVED MASTER-PLAN-v2...');
console.log('[steward-stage2] NS=', NS_PATH, ' plan=', PLAN_PATH);

try {
  const result = await runStage2({
    agent,
    northStar,
    masterPlan,
    criteria,
    depth: 'FULL',
    outputDir: OUT + '/handoff',
    artifactsDir: OUT + '/stage2-artifacts',
    statusLog: OUT + '/_crucible-status-stage2.log',
    routes,
    log: (m) => console.log('[stage2]', m),
  });

  writeFileSync(
    OUT + '/stage2-result.json',
    JSON.stringify(
      {
        handed_off: !!(result && result.handedOff !== false),
        approved: result && result.approved,
        roundsRun: result && result.loop ? result.loop.roundsRun : result?.roundsRun ?? 'n/a',
        families: [...(tracker && tracker.families ? tracker.families() : [])],
        routes,
        ts: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  console.log('[steward-stage2] DONE — see handoff/ and stage2-result.json');
} catch (e) {
  writeFileSync(OUT + '/stage2-ERROR.txt', String((e && e.stack) || e));
  console.log('[steward-stage2] HALT/ERROR:', e && e.message);
  console.log(
    '[steward-stage2] (round-cap / human-approval HALT is normal — best draft + open findings in stage2-artifacts/)',
  );
}

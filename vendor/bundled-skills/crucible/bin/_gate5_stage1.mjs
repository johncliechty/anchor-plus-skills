import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage1 } from './stage1.mjs';

// Gate 5 — Conversational Kickoff Synthesis v0 — Stage 1 (Master Plan), LITE band.
// North Star LOCKED by John (see NORTH-STAR-LOCKED.md); intake at
// <path> Launched via the schtasks
// breakaway (journal 0090); this launcher logs to stderr only — the .cmd wrapper owns the file.
const OUT = '<path>';
const s0 = JSON.parse(readFileSync(OUT + '/stage0-result.json', 'utf8'));
if (!s0.approved || !s0.lock || !s0.lock.locked) {
  console.error('[gate5-stage1] REFUSED: North Star is not locked (run _gate5_stage0.mjs --approved after John locks it)');
  process.exit(2);
}
const { northStar, criteria, nonGoals, riskTaxonomy, foresightBrief } = s0.framing;
const proposal = readFileSync('<path>', 'utf8');
const review = readFileSync('<path>', 'utf8');
const intake = readFileSync('<path>', 'utf8');

const northStarDoc =
  northStar +
  '\n\nNON-GOALS (v0): ' + nonGoals.join('; ') +
  '\n\nRISK TAXONOMY: ' + riskTaxonomy.join(' | ') +
  '\n\nFORESIGHT: ' + foresightBrief +
  '\n\n=== CONTROLLING PROPOSAL (LOCKED design; the six Fable corrections are already folded in) ===\n' + proposal +
  '\n\n=== FABLE ADVERSARIAL REVIEW (approve with six required changes — all incorporated) ===\n' + review +
  '\n\n=== INTAKE (scope, locked inputs, Foreman expectations) ===\n' + intake;

const acceptanceCriteria = [
  'BASE IS GREEN AND REUSED, NOT FORKED: engine/kickoff.mjs (963 lines, id-rename fix 0097, WH4 12/12) + test/kickoff-synthesis-v0.test.mjs + test/wh4-conversational-steward.test.mjs are the starting point; the plan names what it KEEPS, what it CHANGES, and what it DELETES from that base (a replaced surface names the deletion).',
  'TWO-REPO SCOPE, HONEST: Ecgberht (engine + seal-chamber-bridge kickoff-show/confirm/replay verbs + tests) first; then a THIN Anchor cockpit canary (steward_cockpit/) that renders open AND confirmed proposals from the lineage — reader ships in the same slice; dist_manifest rows for every new file; chamber/routes-inventory.json rows for the three kickoff verbs must replace the declared not_exposed exception with real exposed_via routes when the canary exposes them.',
  'HARDENING LAW: every asserted property (hash-bound idempotent confirm, stale-confirm refusal, no authoritative write before confirm, restart paints open/confirmed, no execution leakage, no precondition prompt) EMITS a mechanical gate — a named test the orchestrator runs; every surface-bearing wave carries a failure-state table with "unknown" and "empty" as different rows.',
  'LIVE SEATS ARE JOHN\'S CALL: hermetic tape-backed tests by default; any live ChatGPT/Codex or Claude seat recording is a named wave step that halts for John\'s explicit go.',
  'THE LAST GATE IS HIS SCREEN: acceptance #13 (30-second test across five synthetic efforts) is verified by John on his screen after an Anchor restart he performs — the plan schedules it as a human step, never a test.',
  'ELEGANCE: the plan names something it CUT; no element without a needed-because line; no new user workflow, form, wizard, or graph editor.',
];

mkdirSync(OUT + '/stage1-artifacts', { recursive: true });
console.error('[gate5-stage1] building live cross-family agent...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.error('[gate5-stage1] agent built; routes=', JSON.stringify(routes));
console.error('[gate5-stage1] starting runStage1 (LITE)...');

try {
  const result = await runStage1({
    agent,
    northStar: northStarDoc,
    criteria,
    acceptanceCriteria,
    depth: 'LITE',
    artifactsDir: OUT + '/stage1-artifacts',
    statusLog: OUT + '/_crucible-status.log',
    routes,
    log: (m) => console.error('[stage1]', m),
  });
  writeFileSync(OUT + '/stage1-result.json', JSON.stringify(result, null, 2));
  const plan = result.plan || {};
  const loop = result.loop || {};
  writeFileSync(OUT + '/MASTER-PLAN-DRAFT.md', [
    '# Master Plan (DRAFT) — Conversational Kickoff Synthesis v0',
    '', "_Crucible Stage 1 (LITE, cross-family). DRAFT for John's approval._", '',
    '## Convergence',
    '- converged: ' + JSON.stringify(loop.converged ?? loop.status ?? 'see stage1-result.json'),
    '- rounds: ' + JSON.stringify(loop.rounds ?? loop.round ?? 'n/a'),
    '- open findings: ' + JSON.stringify((loop.openFindings || loop.findings || []).length ?? 'n/a'),
    '- families reached: ' + JSON.stringify([...(tracker && tracker.families ? tracker.families() : [])]),
    '', '## Phased plan', '```json', JSON.stringify(plan, null, 2), '```',
  ].join('\n'));
  console.error('[gate5-stage1] DONE — MASTER-PLAN-DRAFT.md + stage1-result.json written');
} catch (e) {
  writeFileSync(OUT + '/stage1-ERROR.txt', String((e && e.stack) || e));
  console.error('[gate5-stage1] HALT/ERROR:', e && e.message);
  console.error('[gate5-stage1] (a human-lockable HALT is normal — best draft + OPEN-FINDINGS persist in stage1-artifacts/)');
}

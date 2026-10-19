// stage2-driver.mjs — Crucible Stage 2, part A (decompose + vet), for the Anchor
// re-architecture. Master Plan was APPROVED by John 2026-07-03. This driver runs
// wave decomposition (frontier Claude) + the Shark-Tank vetting loop (GEMINI
// sharks — the standing 5:1 rule) over the rendered Implementation Plan, then
// STOPS at John's implementation-plan approval gate, persisting everything to
// disk (waves.json + the vetted draft) so part B (emission + well-formedness
// gate + Foreman handoff) runs after his approval without redoing the loop.
import fs from 'node:fs';
import path from 'node:path';

const DIR = 'C:/dev/Anchor/planning/crucible-rearchitecture-2026-07';
const ART = path.join(DIR, 'stage2-artifacts');
fs.mkdirSync(ART, { recursive: true });
const log = (line) => {
  fs.appendFileSync(path.join(DIR, 'STATUS.log'), `[${new Date().toISOString()}] ${line}\n`);
};

const { decomposeIntoWaves, renderImplementationPlan } = await import('file:///C:/dev/trio/crucible/bin/stage2.mjs');
const { runMasterPlanLoop } = await import('file:///C:/dev/trio/crucible/bin/stage1.mjs');
const { makeRoleRoutedAgent } = await import('file:///C:/dev/trio/drivers/index.mjs');

const agent = makeRoleRoutedAgent({
  routes: {
    shark: { driver: 'gemini-cli', model: 'gemini-3.1-pro' },
    default: { driver: 'claude', model: 'claude-fable-5' },
  },
  env: { ...process.env, CRUCIBLE_AGENT_LIVE: '1' },
  target: 'C:/dev/Anchor',
  log,
});

const northStar = fs.readFileSync(path.join(DIR, 'NORTH-STAR.md'), 'utf8');
const masterPlan = fs.readFileSync(path.join(DIR, 'MASTER-PLAN-DRAFT.md'), 'utf8');
const TEST_COMMAND = 'python -m pytest tests/test_rearch_2026_07.py tests/test_review_fixes_2026_07.py tests/test_model_flex_w8.py -v';

log('=== Crucible STAGE 2 part A — wave decomposition (fable-5) + shark vetting (GEMINI, 5:1 rule) ===');

// (1) Decompose the approved Master Plan into Foreman waves.
const waves = await decomposeIntoWaves({ agent, northStar, masterPlan, log });
fs.writeFileSync(path.join(ART, 'waves.json'), JSON.stringify(waves, null, 2));
log(`decomposition: ${waves.length} wave(s) — persisted to stage2-artifacts/waves.json`);

// (2) Render the Foreman-ready plan; the loop vets THIS human-readable draft.
const plan = renderImplementationPlan({
  title: 'Anchor Re-architecture — the Butler substrate',
  northStar, waves, testCommand: TEST_COMMAND,
});
fs.writeFileSync(path.join(ART, 'impl-plan-prevet.md'), plan);

// (3) Shark-Tank loop to model-side convergence (Gemini sharks; cap = safety ceiling).
let loop = null;
let halted = null;
try {
  loop = await runMasterPlanLoop({
    agent, northStar, draft: plan, roundCap: 3, artifactsDir: ART, log,
  });
} catch (e) {
  halted = { message: e?.message ?? String(e) };
  log(`stage2 loop HALT: ${halted.message}`);
}

const finalPlan = loop?.draft ?? plan;
fs.writeFileSync(path.join(DIR, 'IMPLEMENTATION-PLAN-DRAFT.md'), finalPlan);
fs.writeFileSync(path.join(DIR, 'STAGE2-SUMMARY.md'), [
  '# Stage 2 part A summary (' + new Date().toISOString().slice(0, 10) + ')',
  '',
  `- Waves decomposed: ${waves.length} (stage2-artifacts/waves.json)`,
  loop
    ? `- Vetting: model-side CONVERGED (${loop.roundsRun} round(s); judge ${loop.judgeVerdict?.decision ?? 'n/a'})`
    : `- Vetting: cap-HALT (${halted?.message ?? 'unknown'}) — rounds' artifacts in stage2-artifacts/;`,
  loop ? '' : '  John is the convergence authority.',
  `- Gate command declared: ${TEST_COMMAND}`,
  '- AWAITING: John\'s implementation-plan approval → part B (emit doc trio into the',
  '  build worktree, run locate-plan well-formedness gate, hand off to Foreman 5:1).',
].join('\n'));
log(`=== Stage 2 part A finished — ${loop ? 'CONVERGED' : 'CAP-HALT'} · awaiting John's implementation-plan approval ===`);
process.exit(0);

// stage1-resume-driver.mjs — WARM resume of Crucible Stage 1 after the 2026-07-02
// engine death (the original node process was reaped mid-revise; rounds 1-3
// artifacts survived on disk). Flow:
//   1. ONE frontier-Claude call reconstructs the current-best draft from
//      initial-draft.md + the three rounds' SYNTHESIS directions (the revised
//      drafts only lived in the dead process's memory).
//   2. runMasterPlanLoop re-enters at round 4 (roundCap 2 more — the safety
//      ceiling; a cap-halt hands the decision to John, the convergence authority).
// 5:1 GLOBAL RULE (John, 2026-07-02): sharks route to gemini-cli; every other
// seat (synthesizer, judge, revise, fresh-eyes) stays on claude-fable-5.
import fs from 'node:fs';
import path from 'node:path';

const DIR = 'C:/dev/Anchor/planning/crucible-rearchitecture-2026-07';
const ART = path.join(DIR, 'stage1-artifacts');
const log = (line) => {
  const msg = `[${new Date().toISOString()}] ${line}\n`;
  fs.appendFileSync(path.join(DIR, 'STATUS.log'), msg);
};

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
const initialDraft = fs.readFileSync(path.join(ART, 'initial-draft.md'), 'utf8');
const syntheses = [1, 2, 3].map((r) =>
  `=== ROUND ${r} SYNTHESIS ===\n` +
  fs.readFileSync(path.join(ART, `round-${r}`, 'SYNTHESIS.md'), 'utf8'));

log('=== Stage 1 WARM RESUME — reconstructing draft from rounds 1-3 artifacts; sharks on GEMINI (5:1 global rule) ===');

// (1) Reconstruction — frontier Claude applies the recorded directions.
const reconstructed = await agent([
  'You are the Crucible STAGE-1 draft-reconstruction step. The engine died mid-run;',
  'the revised drafts were lost, but the INITIAL draft and the Synthesizer\'s',
  'per-round directions survive. Rebuild the CURRENT-BEST Master-Plan draft:',
  'apply every direction/dispute-resolution below to the initial draft, in round',
  'order, WITHOUT drifting from the North Star. Return ONLY the full revised',
  'Master-Plan draft as markdown (no preamble).',
  '',
  '=== THE NORTH STAR (verbatim) ===', northStar, '=== END NORTH STAR ===',
  '',
  '=== INITIAL DRAFT ===', initialDraft, '=== END INITIAL DRAFT ===',
  '',
  ...syntheses,
].join('\n'), { label: 'stage1:reconstruct', role: 'revise' });

fs.writeFileSync(path.join(ART, 'reconstructed-draft-r4.md'), String(reconstructed));
log(`reconstruction done — ${String(reconstructed).length} chars; entering loop at round 4 (cap 2 more rounds)`);

// (2) Re-enter the loop: 2 more rounds max; Gemini sharks; cap-halt => John decides.
let result = null;
let halted = null;
try {
  result = await runMasterPlanLoop({
    agent,
    northStar,
    draft: String(reconstructed),
    startRound: 4,
    roundCap: 2,
    artifactsDir: ART,
    log,
  });
} catch (e) {
  halted = { name: e?.name, message: e?.message, reason: e?.reason ?? null };
  log(`loop HALT: ${halted.message}`);
}

const finalDraft = result?.draft ?? String(reconstructed);
fs.writeFileSync(path.join(DIR, 'MASTER-PLAN-DRAFT.md'), finalDraft);
fs.writeFileSync(path.join(DIR, 'STAGE1-SUMMARY.md'), [
  '# Stage 1 summary (warm resume, 2026-07-02)',
  '',
  `- Original run: rounds 1-3 (all DRY, 0 blockers) on Fable 5; engine died mid revise:r3.`,
  `- Resume: draft reconstructed from round syntheses by frontier Claude; rounds 4+ ran with`,
  `  GEMINI sharks (5:1 global rule), synthesizer/judge/revise on claude-fable-5.`,
  result
    ? `- OUTCOME: model-side CONVERGED — judge ${result.judgeVerdict?.decision ?? 'n/a'}; rounds run this resume: ${result.roundsRun}.`
    : `- OUTCOME: round-cap HALT (${halted?.message ?? 'unknown'}) — John is the convergence authority;`,
  result ? '' : '  the draft + full round artifacts are ready for his manual approval/amendment.',
  '',
  '- Draft: MASTER-PLAN-DRAFT.md · artifacts: stage1-artifacts/ (rounds 1-N)',
].join('\n'));
log(`=== Stage 1 resume finished — ${result ? 'CONVERGED' : 'CAP-HALT (John decides)'} ===`);
process.exit(0);

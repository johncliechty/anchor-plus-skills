// Live Stage-2 launcher for the Tidy-Idy GUI effort (adapted from launch-zombie-stage2.mjs).
// Seats from coding/review family prefs (no hardcoded Claude).
import fs from 'node:fs';
import path from 'node:path';
import { buildLiveCrucibleAgent } from './bin/enhanced.mjs';
import { runStage2 } from './bin/stage2.mjs';

const outputDir = 'C:/dev/plans/2026-07-tidy-idy-gui';
const statusLog = path.join(outputDir, '_crucible-status.log');
const artifactsDir = path.join(outputDir, 'artifacts-stage2');
fs.mkdirSync(artifactsDir, { recursive: true });

const northStar = `Make a project's Tidy-Idy button in Anchor launch a background hygiene pass and open a project-tied Triage Panel presenting everything found — files to REMOVE, files to SAVE/COMMIT, and folder REORGANIZATIONS — as human-approvable decisions, applying only what the human approves (ONE git commit per Apply for git-held content, and a reversible Trash move for content git does not hold; undo = git revert for git-held content, restore-from-Trash otherwise — always fully reversible, never a destructive delete), never losing work and never acting without approval. The tidy-idy engine is EXTENDED, NOT FORKED, to add save-detection and reorg proposals and to run on ordinary (non-Foundry, possibly non-git) folders while preserving its removal pipeline and every safety invariant.`;

const criteria = [
  "One-click background run, project-scoped: clicking Tidy-Idy on project P starts a headless run over P's folder (like Gandalf), live running state, and on completion opens a Triage Panel whose header identifies P (name+path+git status+run#); never touches another project.",
  "Three finding classes from real analysis: removals with the real Attacker+Judge verdict; save/commit candidates (untracked + uncommitted); reorg proposals as before->after trees. A failed analysis shows LOUDLY, never fake-clean.",
  "Nothing applied without approval: per-item/per-set approval then Apply = one git commit for git-held changes + an atomic reversible Trash move-set for non-git-held removals (undo = git revert / restore-from-Trash); protected classes never offered for removal.",
  "Runs on ordinary folders honestly: no North-Star file -> labelled heuristics; non-git -> removals work via Trash (Bootstrap/git-init optional, not a gate), Bootstrap runs secret-triage first so no secret lands in the baseline; dirty tree handled not refused.",
  "Extend-don't-fork + green: reuses tidy-idy scanner/hygiene/analyze/debate/remove/compress + Anchor job_runner/Gandalf + Zombie-Sentinel-style serving; suites green; existing substrate first.",
  "Investigator terminal tile (like Zombie Hunter): panel tile opens a seeded terminal (Claude, toggle Gemini) with the tidy-idy skill + a briefing of the CURRENT report, tied to the project.",
  "Report archive/history: every run's report persisted per project newest-first (Gandalf run-index); previous reports kept as browsable references, never overwritten.",
];

const acceptanceCriteria = [
  "every wave carries a testable done-when (+ Given/When/Then for non-trivial waves)",
  "the emitted doc-trio passes Foreman's locate-plan well-formedness gate with zero HALTs",
  "the Trash undo-model, Bootstrap secret-triage, and the adopted hardening (symlink/CSRF/temp-index blobs) each land in a named wave",
];

async function main() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  process.env.GEMINI_MODEL = 'Gemini 3.1 Pro (High)';
  process.env.TRIO_TIER = 'heavy';

  const log = (m) => { const line = typeof m === 'string' ? m : JSON.stringify(m); fs.appendFileSync(statusLog, line + '\n'); };
  log(`[launch] Tidy-Idy STAGE-2 · ${new Date().toISOString()} · seats from coding/review family prefs`);

  const { agent, routes: CRUCIBLE_ROUTES, drafterFamily } = await buildLiveCrucibleAgent({
    env: process.env, target: outputDir, log,
  });
  log(`[launch] drafterFamily=${drafterFamily} routes=${JSON.stringify(CRUCIBLE_ROUTES)}`);

  const masterPlan = fs.readFileSync(path.join(outputDir, 'MASTER-PLAN.md'), 'utf-8');
  log('[stage2] decompose -> Shark-Tank loop -> emit doc-trio -> well-formedness gate');

  const res = await runStage2({
    agent, northStar, masterPlan, criteria,
    title: 'Tidy-Idy GUI + full-vision engine',
    summary: 'Anchor-launched, project-tied Tidy-Idy Triage Panel (remove/save/reorg) with git+Trash reversible safety.',
    outputDir, depth: 'FULL', acceptanceCriteria, artifactsDir, statusLog, routes: CRUCIBLE_ROUTES, log,
  });
  fs.writeFileSync(path.join(outputDir, '_stage2-result.json'), JSON.stringify({ ok: true, ...(res && { keys: Object.keys(res) }) }, null, 2), 'utf8');
  log('[stage2] emitted doc-trio + passed well-formedness gate — HALT for user approval (Foreman handoff)');
}

main().catch((err) => {
  const isHalt = err && (err.name === 'HaltError' || /HaltError|round cap|approv/i.test(String(err.message)));
  const msg = isHalt ? `[stage2 HALT] ${err.message}\n` : `[HALT ERROR] ${err && err.stack || err}\n`;
  try { fs.appendFileSync(statusLog, msg); } catch {}
  console.error(msg);
  process.exit(isHalt ? 0 : 1);
});

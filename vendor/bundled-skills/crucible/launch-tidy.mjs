// Live Stage-1 launcher for Tidy-Idy GUI — MUST use runStage1 so LITE/SPIKE/FULL
// band profiles apply (cf-slick / journal 0028: do not bypass with bare brainstorm+loop).
import fs from 'node:fs';
import path from 'node:path';
import { buildLiveCrucibleAgent } from './bin/enhanced.mjs';
import { runStage1 } from './bin/stage1.mjs';

const outputDir = process.env.CRUCIBLE_OUTPUT_DIR || 'C:/dev/plans/2026-07-tidy-idy-gui';
const statusLog = path.join(outputDir, '_crucible-status.log');
const artifactsDir = path.join(outputDir, 'artifacts');
fs.mkdirSync(artifactsDir, { recursive: true });

// Default LITE for tidy polish-class work; override with CRUCIBLE_DEPTH=FULL|SPIKE-FIRST
const depth = (process.env.CRUCIBLE_DEPTH || 'LITE').toUpperCase();

const northStar = `Make a project's Tidy-Idy button in Anchor launch a background hygiene pass and open a project-tied Triage Panel presenting everything found — files to REMOVE, files to SAVE/COMMIT, and folder REORGANIZATIONS — as human-approvable decisions, applying only what the human approves as ONE git commit per Apply (undo = git revert), never losing work git holds and never acting without approval. The tidy-idy engine is EXTENDED, NOT FORKED, to add save-detection and reorg proposals and to run on ordinary (non-Foundry, possibly non-git) folders while preserving its removal pipeline and every safety invariant.`;

const criteria = [
  'One-click background run, project-scoped',
  'Three finding classes from real analysis',
  'Nothing applied without approval',
  'Runs on ordinary folders honestly',
  'Extend-dont-fork + green',
];

async function main() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  const log = (m) => {
    const line = typeof m === 'string' ? m : JSON.stringify(m);
    fs.appendFileSync(statusLog, line + '\n');
    console.log(line);
  };
  log(`[launch] Tidy-Idy Stage-1 · depth=${depth} · ${new Date().toISOString()}`);

  const { agent, routes: CRUCIBLE_ROUTES, drafterFamily } = await buildLiveCrucibleAgent({
    env: process.env, target: outputDir, log,
  });
  log(`[launch] drafterFamily=${drafterFamily} routes=${JSON.stringify(CRUCIBLE_ROUTES)}`);

  try {
    const result = await runStage1({
      agent,
      northStar,
      criteria,
      depth,
      approved: false,
      routes: CRUCIBLE_ROUTES,
      artifactsDir,
      statusLog,
      log,
    });
    const draft = result?.loop?.finalDraft || result?.loop?.draft;
    if (draft) fs.writeFileSync(path.join(outputDir, 'MASTER-PLAN-DRAFT.md'), String(draft), 'utf8');
    fs.writeFileSync(path.join(outputDir, '_stage1-result.json'), JSON.stringify({
      band: result?.band, roundsRun: result?.loop?.roundsRun, converged: !!result?.loop?.converged,
    }, null, 2));
    log('[stage1] completed without HALT (unexpected if approved:false)');
  } catch (err) {
    const msg = `[HALT] ${err?.reason || err?.message || err}\n`;
    fs.appendFileSync(statusLog, msg);
    if (err?.best_draft?.draft) {
      fs.writeFileSync(path.join(outputDir, 'MASTER-PLAN-DRAFT.md'), String(err.best_draft.draft), 'utf8');
    }
    console.error(msg);
    process.exit(err?.halt_for_human ? 3 : 1);
  }
}

main();

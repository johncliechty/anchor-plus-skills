// Live Stage-1 launcher — always runStage1 (band profiles apply; cf-slick).
import fs from 'node:fs';
import path from 'node:path';
import { buildLiveCrucibleAgent } from './bin/enhanced.mjs';
import { runStage1 } from './bin/stage1.mjs';

const outputDir = process.env.CRUCIBLE_OUTPUT_DIR || 'C:/dev/plans/2026-07-zombie-hunter-ux';
const statusLog = path.join(outputDir, '_crucible-status.log');
const artifactsDir = path.join(outputDir, 'artifacts');
fs.mkdirSync(artifactsDir, { recursive: true });
const depth = (process.env.CRUCIBLE_DEPTH || 'FULL').toUpperCase();

const northStar = process.env.CRUCIBLE_NORTH_STAR ||
  'Ship a safe-to-arm zombie-hunter UX that only freezes/kills proven orphans.';

const criteria = (process.env.CRUCIBLE_CRITERIA || 'safety;abstain-default;clear UX').split(';');

async function main() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  const log = (m) => {
    const line = typeof m === 'string' ? m : JSON.stringify(m);
    fs.appendFileSync(statusLog, line + '\n');
    console.log(line);
  };
  log(`[launch] Stage-1 · depth=${depth} · ${new Date().toISOString()}`);
  const { agent, routes } = await buildLiveCrucibleAgent({ env: process.env, target: outputDir, log });
  try {
    const result = await runStage1({
      agent, northStar, criteria, depth, approved: false, routes, artifactsDir, statusLog, log,
      spikeProbe: process.env.CRUCIBLE_SPIKE_PROBE || null,
    });
    fs.writeFileSync(path.join(outputDir, '_stage1-result.json'), JSON.stringify({ band: result?.band }, null, 2));
  } catch (err) {
    fs.appendFileSync(statusLog, `[HALT] ${err?.reason || err?.message}\n`);
    if (err?.best_draft?.draft) {
      fs.writeFileSync(path.join(outputDir, 'MASTER-PLAN-DRAFT.md'), String(err.best_draft.draft), 'utf8');
    }
    process.exit(err?.halt_for_human ? 3 : 1);
  }
}

main();

import fs from 'node:fs';
import path from 'node:path';
import { buildLiveCrucibleAgent } from './bin/enhanced.mjs';
import { runStage2 } from './bin/stage2.mjs';

const outputDir = path.resolve(process.cwd(), 'zombie-crucible-output');
const artifactsDir = path.join(outputDir, 'artifacts');
const statusLog = path.join(outputDir, '_crucible-status.log');

const northStar = `Transform Zombie Hunter from an Anchor-specific utility into a global, system-wide AI process sentinel. 
Key objectives:
1. System-Wide Detection: Expand scope to monitor and track all AI-related processes across the OS (including Anchor, VS Code AI swarms, raw terminal processes, and cowork).
2. GUI Enhancements: Add a manual "Relaunch Sweep" button to the GUI for on-demand, fresh process updates.
3. Historical Forensics: Introduce a retrospective analysis feature that identifies evidence of past zombie swarms that consumed resources but evaded detection.
4. Human-in-the-Loop Approval: Replace automated kills with a human-facing approval workflow that freezes the rogue swarm. Include a toggleable "Show Context" button in the GUI to reveal (and hide) the detailed, human-readable explanation of what the process is and why it should be neutralized.`;

const criteria = [
    "System-wide detection across Anchor, VS Code, terminals, and cowork is functional",
    "GUI contains a working Relaunch Sweep button",
    "Forensics feature successfully identifies past undetected zombies",
    "Human-in-the-loop kill workflow is active with a Show Context toggle"
];

async function main() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  process.env.GEMINI_MODEL = 'Gemini 3.1 Pro (High)';
  process.env.TRIO_TIER = 'heavy';

  const log = (m) => {
    console.log(m);
    fs.appendFileSync(statusLog, m + '\n');
  };
  
  const { agent, routes, drafterFamily } = await buildLiveCrucibleAgent({
    env: process.env,
    target: process.cwd(),
    log,
  });
  log(`routes=${JSON.stringify(routes)} drafterFamily=${drafterFamily}`);
  
  const masterPlan = fs.readFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), 'utf-8');
  
  log("Starting Stage 2 Implementation Plan (FULL Depth)...");
  
  const res = await runStage2({
    agent, 
    northStar, 
    masterPlan,
    criteria,
    outputDir,
    depth: 'FULL',
    // approved is intentionally NOT set: the user locks the Implementation Plan (North-Star you-approve gate).
    artifactsDir,
    statusLog,
    routes,
    log
  });
  
  log("Stage 2 completed!");
}

main().catch(err => {
  const msg = `HALT ERROR: ${err.message}\n`;
  console.error(msg);
  fs.appendFileSync(statusLog, msg);
});

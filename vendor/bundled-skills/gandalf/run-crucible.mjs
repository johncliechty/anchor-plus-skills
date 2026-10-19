import fs from 'node:fs';
import path from 'node:path';

import { makeGeminiCliSeam as makeAgentSeam, resolveGeminiModel } from 'fil<path>';

// Explicitly set the environment variables as requested by the user and Global Skill Model Rule.
// W4 (2026-07-05): the model is the CURRENT agy LABEL resolved via the TRIO_TIER ladder — NEVER a
// hardcoded API-style id (the old hardcoded default was a PHANTOM id that live agy silently degraded
// to Flash).
process.env.CRUCIBLE_AGENT_LIVE = '1';
process.env.TRIO_DRIVER = 'gemini-cli';
const RESOLVED_GEMINI_MODEL = resolveGeminiModel({ env: process.env });
process.env.TRIO_MODEL = RESOLVED_GEMINI_MODEL;
process.env.GEMINI_MODEL = RESOLVED_GEMINI_MODEL;
import { runStage0 } from 'fil<path>';
import { runBrainstorm, triageIdeas, buildPhasedPlan, renderMasterPlanDraft, runMasterPlanLoop } from 'fil<path>';

const TARGET = process.cwd();
const outputDir = path.join(TARGET, 'planning', 'crucible-scale2');
const INTENT = "Make Gandalf robust for massive codebases (specifically the Map-Reduce synthesis engine and Agentic Scout pass).";

async function run() {
  console.log('=== GANDALF CRUCIBLE LIVE RUN ===');
  fs.mkdirSync(outputDir, { recursive: true });
  
  const agent = makeAgentSeam({ env: process.env, target: TARGET, log: console.log }).agent;
  
  try {
    const stage0 = await runStage0({ intent: INTENT, input: { kind: 'greenfield' }, agent, approved: true, log: console.log });
    const northStar = stage0.lock.northStar;
    const criteria = stage0.lock.criteria;
    fs.writeFileSync(path.join(outputDir, 'DRAFT-NORTH-STAR.md'), northStar);
    
    const brainstorm = await runBrainstorm({ agent, northStar, criteria, log: console.log });
    const triage = triageIdeas({ ideas: brainstorm.ideas, log: console.log });
    const phased = await buildPhasedPlan({
      agent, northStar, criteria,
      ideas: triage.integrate, assumptions: brainstorm.assumptions, premortem: brainstorm.premortem, log: console.log,
    });
    
    let draft = renderMasterPlanDraft(phased);
    fs.writeFileSync(path.join(outputDir, 'DRAFT-MASTER-PLAN.md'), draft);

    const loop = await runMasterPlanLoop({
      agent, northStar, criteria, draft,
      acceptanceCriteria: ['Passes tests'], artifactsDir: path.join(TARGET, 'journal'), log: console.log,
    });
    
    console.log('\n=== CRUCIBLE RUN COMPLETED ===');
  } catch (e) {
    if (e.name === 'HaltError') {
      console.log(`\n=== HALTED FOR HUMAN APPROVAL ===`);
      console.log(`Reason: ${e.message}`);
      console.log(`Pending Action: ${e.pending_action || 'none'}`);
    } else {
      console.error(`\n=== FATAL ERROR ===`, e);
    }
  }
}

run();


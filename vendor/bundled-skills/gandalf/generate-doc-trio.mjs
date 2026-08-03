import fs from 'node:fs';
import path from 'node:path';

import { makeGeminiCliSeam as makeAgentSeam, resolveGeminiModel } from 'fil<path>';

// Explicitly set the environment variables.
// W4 (2026-07-05): the model is the CURRENT agy LABEL resolved via the TRIO_TIER ladder — NEVER a
// hardcoded API-style id (the old hardcoded default was a PHANTOM id that live agy silently degraded
// to Flash).
process.env.CRUCIBLE_AGENT_LIVE = '1';
process.env.TRIO_DRIVER = 'gemini-cli';
const RESOLVED_GEMINI_MODEL = resolveGeminiModel({ env: process.env });
process.env.TRIO_MODEL = RESOLVED_GEMINI_MODEL;
process.env.GEMINI_MODEL = RESOLVED_GEMINI_MODEL;
import { runStage2 } from 'fil<path>';

const TARGET = process.cwd();
const outputDir = path.join(TARGET, 'planning', 'crucible-scale2');

const northStar = fs.readFileSync(path.join(outputDir, 'DRAFT-NORTH-STAR.md'), 'utf-8');
const masterPlan = fs.readFileSync(path.join(outputDir, 'DRAFT-MASTER-PLAN.md'), 'utf-8');
const criteria = ["reliably scales to multi-million token codebases", "hierarchical chunking", "rate-limit resilience", "incremental change detection", "robust, token-balanced, and schema-guaranteed analysis pipeline"];

async function run() {
  console.log('=== GANDALF CRUCIBLE STAGE 2 (USER DIRECTED) ===');
  
  const agent = makeAgentSeam({ env: process.env, target: TARGET, log: console.log }).agent;
  
  try {
    const stage2 = await runStage2({
      agent,
      northStar,
      masterPlan,
      criteria,
      outputDir,
      title: 'Gandalf Map-Reduce Engine',
      summary: 'Robust synthesis engine for massive codebases.',
      acceptanceCriteria: ['Passes locate-plan with zero HALTs'],
      approved: true,
      artifactsDir: path.join(TARGET, 'journal'),
      log: console.log
    });
    
    console.log('\n=== STAGE 2 COMPLETED ===');
    console.log('Doc-trio successfully generated in: ' + stage2.docTrio.dir);
  } catch (e) {
    console.error(`\n=== FATAL ERROR ===`, e);
  }
}

run();

#!/usr/bin/env node
// bin/plan-gate.mjs — wire researchPrime's ACTUAL Phase-1 research plan through the
// human two-gate approval (the "report the plan one-shot; user APPROVEs / EDITs / ABORTs
// before execution" behavior).
//
// Before this seam, the two-gate machine (bin/two-gate.mjs) only ever surfaced the generic
// `planMatrix` boilerplate at Gate 2 — never the rich Phase-1 plan the requester actually
// cares about. This module injects `buildResearchPlan` as the Gate-2 plan artifact so the
// human approves the real thing: AXIS + candidate branches + best-in-class baselines +
// the deterministic stakes vector / governor tier / Oranges foresight receipt.
//
// The plan artifact is a PURE function of the operator's frozen Phase-1 inputs (runPhase1 is
// deterministic; no clock, no randomness), so the same inputs serialize to the same bytes and
// the same planHash — which is what the Gate-2 EDIT re-hash discipline and replay fixtures rely on.

import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

import { runTwoGateMachine } from './two-gate.mjs';
import { runPhase1 } from './phase1.mjs';
import { deriveGovernorContract } from './formal-governor.mjs';
import { HaltError } from './trio-core/contract-core.mjs';

export const RESEARCH_PLAN_VERSION = 'researchPrime-phase1/1';

/**
 * Build the rich Phase-1 research plan artifact the human approves at Gate 2.
 * PURE function of `inputs` (runPhase1 is deterministic) → stable planHash.
 *
 * @param {{inputs: object}} args
 *   inputs: { objective|query, axis?, branches?, baselines?, stakes? }
 * @returns {object} the plan artifact (serialized + hashed by the two-gate machine)
 */
export function buildResearchPlan({ inputs } = {}) {
  const src = inputs || {};
  const objective = src.objective || src.query;
  if (typeof objective !== 'string' || objective.length === 0) {
    throw new TypeError('buildResearchPlan requires a non-empty objective');
  }
  const branches = Array.isArray(src.branches) ? src.branches : [];
  const baselines = Array.isArray(src.baselines) ? src.baselines : [];
  const receipt = runPhase1({ stakes: src.stakes ?? {}, plan: { branches } });
  return {
    planVersion: RESEARCH_PLAN_VERSION,
    objective,
    axis: src.axis ?? null, // the load-bearing win-condition + what FALSIFIES a candidate
    branches, // candidate research branches
    baselines, // best-in-class baselines to beat
    tier: receipt.tier, // governor tier the Phase-3 loop scales by (projection of the stakes vector)
    stakes: receipt.stakes, // carries the verbatim declared vector (`raw`) + axis_tiers
    foresight: receipt.foresight, // Oranges receipt (dropped/reordered branch + counterfactual cost)
  };
}

/**
 * Run the two-gate human approval with the REAL Phase-1 plan at Gate 2.
 * Thin wrapper over runTwoGateMachine that injects `buildResearchPlan`.
 *
 * P0 2026-07-25 (journal 0004): the governance record now locks the REAL governor
 * contract (thresholds/tier/roundBudget via deriveGovernorContract), not the two-gate
 * `{hash:'mock-hash'}` placeholder — the placeholder short-circuited run-rounds'
 * `lockedGovernorOutput ||` and crashed at `thresholds.N`, breaking the documented
 * plan-gate → run-rounds happy path end-to-end. `provenance.inputsHash` mirrors to
 * `.hash` to satisfy the governance-record validator. An explicitly-passed
 * `opts.lockedGovernorOutput` still wins (tests / callers with their own lock).
 *
 * @param {object} inputs frozen Phase-1 inputs (see buildResearchPlan)
 * @param {object} opts   forwarded to runTwoGateMachine (runDir, prompts, approvalProvider, …)
 */
export async function runPlanReviewGate(inputs, opts = {}) {
  let lockedGovernorOutput = opts.lockedGovernorOutput;
  if (!lockedGovernorOutput) {
    const contract = deriveGovernorContract(inputs);
    lockedGovernorOutput = { ...contract, hash: contract.provenance.inputsHash };
  }
  return runTwoGateMachine(inputs, { ...opts, lockedGovernorOutput, buildPlan: buildResearchPlan });
}

// ---------------------------------------------------------------------------
// CLI: node bin/plan-gate.mjs <planInputs.json> [runDir]
// Presents the frozen Phase-1 plan to the operator at a TTY and records the
// hash-bound APPROVE/EDIT/ABORT decision as a durable governance record.
// ---------------------------------------------------------------------------

function renderPlan(plan) {
  const lines = [];
  lines.push('──────────────────────────────────────────────────────────────');
  lines.push('  researchPrime — PHASE-1 PLAN (review before execution)');
  lines.push('──────────────────────────────────────────────────────────────');
  lines.push(`  Objective : ${plan.objective}`);
  lines.push(`  AXIS      : ${plan.axis ?? '(none stated)'}`);
  lines.push(`  Stakes    : tier=${plan.tier}`);
  lines.push('  Branches  :');
  for (const b of plan.branches) lines.push(`    - ${typeof b === 'string' ? b : JSON.stringify(b)}`);
  lines.push('  Baselines to beat:');
  for (const b of plan.baselines) lines.push(`    - ${typeof b === 'string' ? b : JSON.stringify(b)}`);
  const dropped = plan.foresight?.dropped ?? plan.foresight?.dropped_or_reordered;
  lines.push(`  Foresight : ${plan.foresight?.stamp ?? JSON.stringify(dropped ?? plan.foresight ?? {})}`);
  lines.push('──────────────────────────────────────────────────────────────');
  return lines.join('\n');
}

async function askDecision(rl, label) {
  const answer = (await rl.question(`${label} — APPROVE / EDIT / ABORT? `)).trim().toUpperCase();
  return ['APPROVE', 'EDIT', 'ABORT'].includes(answer) ? answer : 'ABORT';
}

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}

if (invokedDirectly()) {
  const [planFile, runDirArg] = process.argv.slice(2);
  if (!planFile) {
    console.error('usage: node bin/plan-gate.mjs <planInputs.json> [runDir]');
    process.exit(2);
  }
  const inputs = JSON.parse(fs.readFileSync(planFile, 'utf8'));
  const runDir = runDirArg || path.join(path.dirname(path.resolve(planFile)), 'plan-gate-run');
  fs.mkdirSync(runDir, { recursive: true });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  runPlanReviewGate(inputs, {
    runDir,
    // Gate 1 = confirm scope/intake; Gate 2 = approve the rendered Phase-1 plan (the one-shot report).
    promptGate1: async () => askDecision(rl, `\nScope: ${inputs.objective || inputs.query}`),
    promptGate2: async ({ plan }) => {
      console.log('\n' + renderPlan(plan));
      return askDecision(rl, 'Plan');
    },
  })
    .then((res) => {
      rl.close();
      console.log(`\n✔ Plan APPROVED. planHash=${res.planHash}`);
      console.log(`  governance record → ${path.join(runDir, 'governance.json')}`);
      process.exit(0);
    })
    .catch((err) => {
      rl.close();
      if (err instanceof HaltError || err.name === 'HaltError') {
        console.error(`\n✖ HALTED: ${err.message}`);
        process.exit(1);
      }
      console.error(err);
      process.exit(2);
    });
}

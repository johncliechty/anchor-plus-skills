#!/usr/bin/env node
// run-wave.mjs — drive ONE wave of a project end-to-end with the deterministic
// scripted driver (no LLM). This is the runnable demonstration/validation
// harness for the Phase-1 engine: it reuses the Phase-0 contracts (locateDocs,
// parseWaves, discoverTestCommand) to resolve the wave + ground-truth gate
// command, then calls runWave() from bin/wave-engine.mjs.
//
// In production the same runWave() is driven by Workflow `agent()` calls
// (bin/wave-workflow.js); here the model-driven steps are scripted so the
// red->green transition is reproducible and the gate (the real test command)
// remains the sole source of truth.
//
// Usage:
//   node run-wave.mjs <projectDir> [--wave N] [--cap K] [--reviewers R]
//                     [--repair "<file>:::<findLast>:::<replace>"]... [--forge-green]
//
// Exit codes: 0 wave converged GREEN · 3 HALT-for-human · 2 internal error.

import fs from 'node:fs';
import path from 'node:path';
import {
  HaltError, locateDocs, parseWaves, discoverTestCommand,
} from './foreman-lib.mjs';
import { runWave } from './wave-engine.mjs';
import { makeScriptedDriver } from './drivers/scripted-driver.mjs';

function getFlag(args, name, def) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}
function getAll(args, name) {
  const out = [];
  for (let i = 0; i < args.length; i++) if (args[i] === name && i + 1 < args.length) out.push(args[i + 1]);
  return out;
}

async function main(argv) {
  const args = argv.slice(2);
  const dir = path.resolve(args.find((a) => !a.startsWith('--')) || process.cwd());

  // --- reuse Phase-0 contracts (do not reimplement) ---
  const docs = locateDocs(dir);
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);
  const testCmd = discoverTestCommand(planText, dir);

  // --- select the single target wave (default = terminal wave) ---
  const waveN = args.includes('--wave') ? Number(getFlag(args, '--wave')) : waves[waves.length - 1].n;
  const wave = waves.find((w) => w.n === waveN);
  if (!wave) { process.stderr.write(`no such wave: ${waveN}\n`); return 2; }

  const cap = Number(getFlag(args, '--cap', '4'));
  const reviewers = Number(getFlag(args, '--reviewers', '2'));

  const repairs = getAll(args, '--repair').map((spec) => {
    const [file, findLast, replace] = spec.split(':::');
    return { file, findLast, replace };
  });
  const forgeGreenClaim = args.includes('--forge-green');

  const driver = makeScriptedDriver({ repairs, forgeGreenClaim });

  process.stderr.write(
    `[run-wave] project=${dir}\n` +
    `[run-wave] gate command=${testCmd.command} (source: ${testCmd.source})\n` +
    `[run-wave] wave ${wave.n}/${waves.length} "${wave.title}" · cap=${cap} reviewers=${reviewers}\n`,
  );

  const result = await runWave({
    projectDir: dir,
    testCommand: testCmd.command,
    wave,
    totalWaves: waves.length,
    planPath: docs.plan,
    driver,
    reviewerCount: reviewers,
    fixIterCap: cap,
    log: (s) => process.stderr.write(`  · ${s}\n`),
  });

  process.stdout.write('\n' + result.dashboard + '\n\n');
  process.stdout.write(
    `result: ${result.status}` +
    (result.status === 'HALT' ? ` — ${result.haltReason}` : ` (converged in ${result.iterations} fix iter(s))`) +
    `\ncheckpoint: ${result.checkpointPath}\n` +
    `gate artifact: ${result.gate.artifact_path}\n`,
  );
  return result.status === 'GO' ? 0 : 3;
}

main(process.argv).then((code) => process.exit(code)).catch((e) => {
  if (e instanceof HaltError) {
    process.stderr.write(`HALT: ${e.reason}\n`);
    if (e.detail) process.stderr.write(`      ${e.detail}\n`);
    process.exit(3);
  }
  process.stderr.write(`ERROR: ${e.stack || e.message}\n`);
  process.exit(2);
});

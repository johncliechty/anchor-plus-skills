#!/usr/bin/env node
// run-project.mjs — drive a WHOLE project (every wave, ascending) end-to-end with
// the deterministic scripted driver (no LLM). This is the runnable demonstration /
// validation harness for the Phase-2 multi-wave engine: it reuses the Phase-0
// contracts (locateDocs/parseWaves/discoverTestCommand inside runProject) and the
// Phase-1 one-wave engine (runWave) UNCHANGED, adding only the ascending
// auto-advance loop from bin/project-engine.mjs.
//
// In production the same runProject() is driven by Workflow `agent()` calls
// (bin/wave-workflow.js makeAgentDriver); here the model-driven steps are scripted
// so the multi-wave red->green transition is reproducible and the gate (the real
// test command) stays the sole source of truth.
//
// Usage:
//   node run-project.mjs <projectDir> [--resume] [--reviewers R] [--cap K]
//                        [--max-waves N] [--max-wallclock-sec S]
//                        [--git [--branch NAME]]
//                        [--repair "<file>:::<findLast>:::<replace>"]...   (generic)
//   node run-project.mjs <copyOfCanonicalFixture> --demo-canonical [--resume] [--git]
//
// --git enables Phase-3c git hygiene: each GO wave is committed on a dedicated
//   work branch (default `foreman/run`, override with --branch) AFTER the gate
//   GOes; resume reconciles the checkpoint's last_commit against git HEAD. Foreman
//   NEVER pushes, forces, or rewrites history. Requires <projectDir> to be a repo.
//
// --max-waves / --max-wallclock-sec configure the §4.6 budget as a HARD pre-flight
// gate: the run refuses to START a wave (or a fix iteration) it cannot afford,
// writing a clean, resumable budget-stop checkpoint instead (re-run with --resume).
//
// --demo-canonical is FIXTURE-SPECIFIC demo scaffolding (NOT part of the engine):
//   it stages a temp copy of fixtures/canonical-project to its honest wave-1
//   baseline (the subtract test belongs to wave 2, so it is held back), then drives
//   wave 1 (add/multiply already green) and wave 2 (its EXECUTE adds the subtract
//   test, which fails; its FIX repairs the planted bug) — a faithful 2-wave run
//   over a SINGLE global gate command. The engine (project-engine.mjs) contains no
//   fixture literals; all of that lives here, in the harness.
//
// Exit codes: 0 project DONE · 3 HALT-for-human (error) · 4 BUDGET STOP (clean,
//             resumable) · 2 internal error.

import fs from 'node:fs';
import path from 'node:path';
import { HaltError } from './foreman-lib.mjs';
import { runProject } from './project-engine.mjs';
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

// The planted-bug repair the canonical fixture's wave 2 needs (last `return a + b;`
// in src/calc.js is subtract; add() keeps the first). Same spec Phase 1 used.
const CALC_REPAIR = { file: 'src/calc.js', findLast: 'return a + b;', replace: 'return a - b;' };

/**
 * Stage a temp copy of the canonical fixture to its honest WAVE-1 baseline and
 * return a per-wave driver factory. Wave 1 = no-op (add/multiply already pass).
 * Wave 2 EXECUTE re-adds the held-back subtract test (turning the suite RED), and
 * wave 2 FIX applies the planted-bug repair (turning it GREEN). This models a real
 * project where each wave brings its own feature + test.
 */
const MULTIPLY_DONE = 'return a * b;';
const MULTIPLY_STUB = 'return undefined; // wave 1 to implement: a * b';

function stageCanonicalDemo(projectDir) {
  const testFile = path.join(projectDir, 'test/calc.test.mjs');
  const calcFile = path.join(projectDir, 'src/calc.js');
  const original = fs.readFileSync(testFile, 'utf8');
  // Split off the subtract test block. Prefer its leading comment; fall back to
  // the `test('subtract'...)` call itself.
  let cut = original.search(/\n\/\/ This is the test the planted bug breaks/);
  if (cut < 0) cut = original.search(/\ntest\('subtract/);
  if (cut < 0) throw new HaltError('demo staging failed: subtract test not found in fixture');
  const baseline = original.slice(0, cut) + '\n';
  const subtractBlock = original.slice(cut);
  // Hold back the subtract test => wave-1 baseline tests add + multiply only.
  fs.writeFileSync(testFile, baseline);

  // F2-9: wave 1 must produce a COVERED deliverable, not be a no-op on an
  // already-green suite (a no-op now HALTs: "wave reached green without proving
  // its own deliverable was exercised"). Stage src/calc.js with multiply
  // UN-implemented so wave 1's EXECUTE genuinely writes it — a changed source
  // file the multiply test exercises. This is harness scaffolding, not engine
  // logic; the engine (project-engine.mjs / wave-engine.mjs) is untouched.
  const calcSrc = fs.readFileSync(calcFile, 'utf8');
  if (!calcSrc.includes(MULTIPLY_DONE)) throw new HaltError('demo staging failed: multiply impl not found in fixture');
  fs.writeFileSync(calcFile, calcSrc.replace(MULTIPLY_DONE, MULTIPLY_STUB));

  return function driverFor(wave) {
    if (wave.n === 2) {
      return makeScriptedDriver({
        note: 'implement wave 2: add the subtract test (it fails), then fix the bug',
        repairs: [CALC_REPAIR],
        // EXECUTE re-introduces this wave's test (count rises 2 -> 3: not a weakening).
        onExecute: () => {
          const cur = fs.readFileSync(testFile, 'utf8');
          if (!/test\('subtract/.test(cur)) fs.writeFileSync(testFile, cur + subtractBlock);
        },
      });
    }
    // Wave 1: implement multiply (its deliverable) — a real, test-covered source
    // change, so the wave proves its own work instead of no-op'ing on green.
    return makeScriptedDriver({
      note: 'implement wave 1: core arithmetic (multiply)',
      repairs: [],
      onExecute: () => {
        const cur = fs.readFileSync(calcFile, 'utf8');
        if (cur.includes(MULTIPLY_STUB)) fs.writeFileSync(calcFile, cur.replace(MULTIPLY_STUB, MULTIPLY_DONE));
      },
    });
  };
}

async function main(argv) {
  const args = argv.slice(2);
  const dir = path.resolve(args.find((a) => !a.startsWith('--')) || process.cwd());
  const resume = args.includes('--resume');
  const reviewers = Number(getFlag(args, '--reviewers', '2'));
  const cap = Number(getFlag(args, '--cap', '4'));
  const demo = args.includes('--demo-canonical');

  // §4.6 budget (optional): a HARD pre-flight gate when configured.
  const maxWavesArg = getFlag(args, '--max-waves', null);
  const maxWallSecArg = getFlag(args, '--max-wallclock-sec', null);
  let budgetConfig = null;
  if (maxWavesArg != null || maxWallSecArg != null) {
    budgetConfig = {
      maxWaves: maxWavesArg != null ? Number(maxWavesArg) : null,
      maxWallClockMs: maxWallSecArg != null ? Number(maxWallSecArg) * 1000 : null,
    };
  }

  // Phase 3c git hygiene (opt-in): --git enables commit-on-GO on a dedicated work
  // branch (--branch overrides the default `foreman/run`) + §8 resume reconcile.
  // Never pushes/forces. Off by default (all prior behavior unchanged).
  const useGit = args.includes('--git');
  const branch = getFlag(args, '--branch', null);
  const git = useGit ? (branch ? { branch } : true) : false;

  process.stderr.write(`[run-project] project=${dir}${resume ? ' (resume)' : ''}${useGit ? ' (git)' : ''}\n`);

  let runOpts = {
    projectDir: dir, reviewerCount: reviewers, fixIterCap: cap, resume,
    budgetConfig, git,
    log: (s) => process.stderr.write(`  · ${s}\n`),
  };

  if (demo) {
    runOpts.driverFor = stageCanonicalDemo(dir);
  } else {
    const repairs = getAll(args, '--repair').map((spec) => {
      const [file, findLast, replace] = spec.split(':::');
      return { file, findLast, replace };
    });
    runOpts.driver = makeScriptedDriver({ repairs });
  }

  const result = await runProject(runOpts);

  // Per-wave summary with REAL TAP counts (not exit codes alone).
  process.stdout.write('\n=== per-wave summary ===\n');
  for (const w of result.waveResults) {
    const tap = w.tap || {};
    process.stdout.write(
      `wave ${w.wave} "${w.title}": ${w.status}` +
      ` · gate tests ${tap.tests} pass ${tap.pass} fail ${tap.fail}` +
      ` · ${w.iterations} fix iter(s)` +
      (w.haltReason ? ` · HALT: ${w.haltReason}` : '') + '\n');
  }
  process.stdout.write(`\nresult: ${result.status}`);
  if (result.status === 'HALT') process.stdout.write(` (stopped at wave ${result.stoppedAt}/${result.totalWaves})`);
  else if (result.status === 'BUDGET-STOP') process.stdout.write(` (budget stop [${result.dimension}] at wave ${result.stoppedAt}/${result.totalWaves} — resumable with --resume)`);
  else process.stdout.write(` (all ${result.totalWaves} wave(s) GREEN)`);
  process.stdout.write(`\ncheckpoint: ${result.checkpointPath}\n`);
  if (result.status === 'DONE') return 0;
  if (result.status === 'BUDGET-STOP') return 4;
  return 3;
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

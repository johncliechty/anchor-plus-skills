#!/usr/bin/env node
// locate-plan.mjs — Foreman §4 invocation / confirmation flow (Phase 0).
//
// Runs the deterministic, no-guess part of "inputs / contract at invocation":
//   1. Locate the three frozen docs (description, plan, execution log).
//   2. Parse the wave structure (`## Wave N`) from the plan.
//   3. Discover the build+test command (ground-truth gate source).
//   4. Compute the project-DONE definition.
//   5. State everything back for the user to confirm.
//
// Any missing/ambiguous input is a HALT — Foreman refuses rather than guess
// (§4: "never guess the plan"; §6.4/§6.5 halts).
//
// Usage:
//   node locate-plan.mjs [projectDir]      # default: cwd
//   node locate-plan.mjs --json [dir]      # machine-readable report
//
// Exit codes:
//   0  contract resolved (docs found, waves parsed, test command found)
//   3  HALT-for-human (missing/ambiguous doc, no waves, no test command)
//   2  unexpected internal error

import fs from 'node:fs';
import path from 'node:path';
import {
  HaltError, locateDocs, parseWaves, discoverTestCommand, preflightTestCommand,
  projectDoneDefinition,
} from './foreman-lib.mjs';

function main(argv) {
  const args = argv.slice(2);
  const json = args.includes('--json');
  const dir = path.resolve(args.find((a) => !a.startsWith('--')) || process.cwd());

  // 1. docs
  const docs = locateDocs(dir);
  // 2 + 3 read the plan once
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);
  const rawCmd = discoverTestCommand(planText, dir);
  // cf-slick: same honesty as runProject (broken test/ + under-gate + dual-root)
  const testCmd = preflightTestCommand(rawCmd, dir);
  const done = projectDoneDefinition(waves);

  const report = {
    status: 'OK',
    project_dir: dir,
    docs: {
      description: docs.description,
      plan: docs.plan,
      execution_log: docs.execution_log,
      resolved_via: docs.source,
    },
    waves: waves.map((w) => ({ n: w.n, title: w.title, line: w.line })),
    total_waves: waves.length,
    test_command: testCmd,
    project_done: done,
  };

  if (json) {
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    return 0;
  }

  const rel = (p) => path.relative(dir, p) || p;
  const out = [];
  out.push('Foreman — invocation contract (please confirm before I build):');
  out.push('');
  out.push(`  project folder : ${dir}`);
  out.push(`  docs resolved via: ${docs.source}`);
  out.push(`  • description  : ${rel(docs.description)}`);
  out.push(`  • plan         : ${rel(docs.plan)}`);
  out.push(`  • execution log: ${rel(docs.execution_log)}`);
  out.push('');
  out.push(`  waves parsed   : ${waves.length}`);
  for (const w of waves) {
    out.push(`     ${String(w.n).padStart(2)}. ${w.title || '(untitled)'}   [plan:${w.line}]`);
  }
  out.push('');
  out.push(`  test command   : ${testCmd.command}   (source: ${testCmd.source})`);
  out.push(`  project DONE   : ${done.predicate}`);
  out.push(`                   terminal wave = ${done.last_wave} "${done.last_wave_title}"`);
  out.push('');
  out.push('  → Confirm this is the source of truth, then re-invoke to build.');
  process.stdout.write(out.join('\n') + '\n');
  return 0;
}

try {
  process.exit(main(process.argv));
} catch (e) {
  if (e instanceof HaltError) {
    process.stderr.write(`HALT: ${e.reason}\n`);
    if (e.detail) process.stderr.write(`      ${e.detail}\n`);
    process.stderr.write('      (Foreman refuses to guess — resolve the above and re-invoke.)\n');
    process.exit(3);
  }
  process.stderr.write(`ERROR: ${e.stack || e.message}\n`);
  process.exit(2);
}

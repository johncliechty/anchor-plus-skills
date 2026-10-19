#!/usr/bin/env node
// checkpoint.mjs — Foreman §8 checkpoint IO + §10 dashboard (Phase 0).
//
// Subcommands:
//   new <file> --plan <path> --waves <N> [--reviewers K]
//        write a fresh schema-valid checkpoint atomically.
//   read <file>
//        read + validate; HALT (exit 3) on torn/invalid file.
//   roundtrip <file> --plan <path> --waves <N>
//        write then read back; assert deep-equality; report PASS/FAIL.
//   dashboard <file>
//        render the §10 commentary block from a checkpoint.
//   clear <file>
//        clear a HALTED checkpoint to a clean, resumable budget-stop (human
//        acknowledgment of the blocker). No-op on non-halted checkpoints.
//        Resume still re-proves GREEN through the orchestrator gate.
//
// Exit codes: 0 ok · 3 HALT (invalid checkpoint) · 1 roundtrip mismatch · 2 error

import {
  HaltError, newCheckpoint, writeCheckpointAtomic, readCheckpoint, renderDashboard,
} from './foreman-lib.mjs';
import { clearHaltedCheckpoint } from './project-engine.mjs';
import path from 'node:path';

function flag(args, name, def = undefined) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}

function main(argv) {
  const args = argv.slice(2);
  const cmd = args[0];
  const file = args[1];

  switch (cmd) {
    case 'new': {
      const cp = newCheckpoint({
        plan_path: flag(args, '--plan', 'unknown'),
        total_waves: Number(flag(args, '--waves', '0')),
        reviewer_count: Number(flag(args, '--reviewers', '2')),
      });
      const dest = writeCheckpointAtomic(file, cp);
      process.stdout.write(`wrote checkpoint: ${dest}\n`);
      return 0;
    }
    case 'read': {
      const cp = readCheckpoint(file);
      process.stdout.write(JSON.stringify(cp, null, 2) + '\n');
      return 0;
    }
    case 'roundtrip': {
      const cp = newCheckpoint({
        plan_path: flag(args, '--plan', 'plan.md'),
        total_waves: Number(flag(args, '--waves', '3')),
      });
      // mutate a few fields so the round-trip exercises non-default values
      cp.current_wave = 2;
      cp.intra_wave_step = 'review';
      cp.iteration = 1;
      cp.last_verdict = 'GO';
      cp.last_commit = 'deadbeef';
      cp.open_findings = [{ id: 'src/x.js:42+null-deref', severity: 'MAJOR', file: 'src/x.js', line: 42, rule: 'null-deref', status: 'open' }];
      cp.pending_action = 'fix iter 2';
      writeCheckpointAtomic(file, cp);
      const back = readCheckpoint(file);
      const a = JSON.stringify(cp);
      const b = JSON.stringify(back);
      if (a === b) {
        process.stdout.write('ROUNDTRIP PASS — written and read-back checkpoints are byte-identical\n');
        return 0;
      }
      process.stdout.write('ROUNDTRIP FAIL\n');
      process.stdout.write(`  wrote: ${a}\n  read : ${b}\n`);
      return 1;
    }
    case 'dashboard': {
      const cp = readCheckpoint(file);
      const block = renderDashboard({
        project: path.dirname(path.resolve(cp.plan_path)),
        wave: cp.current_wave,
        totalWaves: cp.total_waves,
        waveTitle: cp.pending_action || cp.intra_wave_step,
        lines: [
          '▸ execute… done (commit ' + (cp.last_commit || '—') + ')',
          '▸ review (' + cp.reviewer_count + ' independent, sequential)…',
          cp.last_verdict ? ('✓ verdict ' + cp.last_verdict) : '… in progress',
        ],
        contextPct: null,
        elapsed: null,
        budgetWaves: `${cp.current_wave}/${cp.budget_remaining.waves} waves`,
        window: 'OK',
      });
      process.stdout.write(block + '\n');
      return 0;
    }
    case 'clear': {
      // Sleep 0076 package 3: vacuous-GREEN clear requires --force (else refused).
      const force = args.includes('--force') || args.includes('--clear-halt-force');
      const r = clearHaltedCheckpoint(file, {
        log: (s) => process.stdout.write(s + '\n'),
        force,
      });
      if (r.refused) {
        process.stderr.write(
          `clear-halt REFUSED (${r.reason || 'policy'}): land import-tested source or pass --force\n`,
        );
        return 3;
      }
      if (r.cleared) {
        process.stdout.write(
          `cleared: wave ${r.wave} halt -> budget_stopped @ ${r.reentry || 'gate'}` +
            (r.clearedHalt ? ` (was: ${r.clearedHalt})` : '') + '\n',
        );
      }
      return 0;
    }
    default:
      process.stderr.write('usage: checkpoint.mjs <new|read|roundtrip|dashboard|clear> <file> [flags]\n');
      return 2;
  }
}

try {
  process.exit(main(process.argv));
} catch (e) {
  if (e instanceof HaltError) {
    process.stderr.write(`HALT: ${e.reason}\n`);
    if (e.detail) process.stderr.write(`      ${e.detail}\n`);
    process.exit(3);
  }
  process.stderr.write(`ERROR: ${e.stack || e.message}\n`);
  process.exit(2);
}

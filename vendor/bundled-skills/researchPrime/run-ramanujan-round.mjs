#!/usr/bin/env node
// DEPRECATED SHIM (T9, 2026-07-11): this driver was promoted to the canonical
// `bin/run-rounds.mjs` (same behavior + the hard --max-rounds budget + the T8
// clean-convergence mode + run capture). Update invocations; this shim forwards.
import { runRounds } from './bin/run-rounds.mjs';

const runDir = process.argv[2];
if (!runDir) { console.error('usage: node run-ramanujan-round.mjs <runDir>  (deprecated — use bin/run-rounds.mjs)'); process.exit(2); }
console.error('NOTE: run-ramanujan-round.mjs is a deprecated shim — use `node bin/run-rounds.mjs <runDir> [--max-rounds N]`.');
runRounds(runDir).catch((err) => { console.error(`run-rounds: ${err?.message ?? err}`); process.exit(1); });

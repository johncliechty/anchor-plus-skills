#!/usr/bin/env node
import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import process from 'node:process';
import { runAgent as trioRunAgent } from '../../../../trio/drivers/index.mjs';
import {
  createJumperSeatingLedger,
  resolveGate3Seating,
  JumperSelfReviewHalt,
  JumperCrossFamilyDegradeHalt,
} from '../../jumper/index.js';
import { runGate3Ping, writeRunRecord, gate3PingOptionsFromEnv } from '../../jumper/bin/jumper-run.mjs';
import { runSuperjump, refuseImplement } from '../index.js';
import { reweight, parseWeightArg } from '../fit.mjs';
import { renderReport } from '../report.mjs';
import { loadExpectations } from '../progress.mjs';

const USAGE =
  'usage: node bin/superjump-run.mjs --input <file> | --problem "<brief>"\n' +
  '       [--candidates N] [--effort auto|highest] [--output out.json] [--control <file>]\n' +
  '       [--reweight "axis w; axis w" --from result.json]\n' +
  '       (no --deadline; the only automatic stop is SUPERJUMP_CALL_TIMEOUT_MS, default 60 min)';

function parseArgs(argv) {
  const o = {
    problem: null, input: null, output: null, candidates: 3, effort: 'auto',
    control: null, reweight: null, from: null, help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--problem') o.problem = argv[++i];
    else if (a === '--input') o.input = argv[++i];
    else if (a === '--output') o.output = argv[++i];
    else if (a === '--candidates') o.candidates = Number(argv[++i]);
    else if (a === '--effort') o.effort = argv[++i];
    else if (a === '--control') o.control = argv[++i];
    else if (a === '--reweight') o.reweight = argv[++i];
    else if (a === '--from') o.from = argv[++i];
    else if (a === '--help' || a === '-h') o.help = true;
    else if (a === '--deadline' || a === '--deadline-min') {
      throw new Error('superjump-run: a --deadline option does not exist');
    }
    else throw new Error(`unknown argument ${JSON.stringify(a)}`);
  }
  if (!Number.isInteger(o.candidates) || o.candidates < 1 || o.candidates > 5) {
    throw new Error('--candidates requires an integer 1–5');
  }
  return o;
}

function skillDir() {
  try { return realpathSync(join(dirname(fileURLToPath(import.meta.url)), '..')); }
  catch { return join(dirname(fileURLToPath(import.meta.url)), '..'); }
}

async function main() {
  let opts;
  try { opts = parseArgs(process.argv.slice(2)); }
  catch (err) { process.stderr.write(`superjump-run: ${err.message}\n${USAGE}\n`); process.exitCode = 2; return; }
  if (opts.help) { process.stdout.write(`${USAGE}\n`); return; }

  if (opts.reweight) {
    if (!opts.from) { process.stderr.write('superjump-run: --reweight requires --from result.json\n'); process.exitCode = 2; return; }
    const src = JSON.parse(readFileSync(opts.from, 'utf8'));
    const next = reweight(src, parseWeightArg(opts.reweight));
    const out = opts.output || opts.from;
    writeFileSync(out, JSON.stringify(next, null, 2));
    if (out.endsWith('.json')) writeFileSync(out.replace(/\.json$/i, '.md'), renderReport(next));
    process.stdout.write(JSON.stringify({ status: 'reweighted', order: next.order }, null, 2) + '\n');
    return;
  }

  let problem = opts.problem;
  if (!problem && opts.input) problem = readFileSync(opts.input, 'utf8');
  if (!problem || !String(problem).trim()) {
    process.stderr.write(`superjump-run: a brief is required (--problem or --input)\n${USAGE}\n`);
    process.exitCode = 2; return;
  }
  const refuse = refuseImplement(problem);
  if (refuse.refused) {
    process.stderr.write(`superjump-run: refused — ${refuse.pointer}\n`);
    process.exitCode = 2; return;
  }
  if (opts.output) mkdirSync(dirname(resolve(opts.output)), { recursive: true });

  const started = new Date().toISOString();
  const t0 = Date.now();
  const seatingLedger = createJumperSeatingLedger();
  const timeoutMs = Number(process.env.SUPERJUMP_CALL_TIMEOUT_MS) || 60 * 60 * 1000;
  const recordFile = writeRunRecord({
    skill: 'superjump',
    tier: `superjump-${opts.candidates}`,
    started, ended: null,
    input: opts.input || '(--problem argv)',
    params: { candidates: opts.candidates, effort: opts.effort, timeoutMs },
    output: opts.output || null,
    result: `IN-FLIGHT — engine started (pid ${process.pid})`,
    duration_s: 0, journal_ref: null,
  }, { skillDir: skillDir() });

  let seating;
  try {
    seating = resolveGate3Seating({ env: process.env, assertIndependent: true });
  } catch (err) {
    process.stderr.write(`superjump-run: HALT (pre-flight) — ${err?.name}: ${err?.message}\n`);
    writeRunRecord({
      skill: 'superjump', tier: `superjump-${opts.candidates}`, started,
      ended: new Date().toISOString(), result: `HALT pre-flight: ${err?.name}`,
      duration_s: Math.round((Date.now() - t0) / 1000),
    }, { skillDir: skillDir(), file: recordFile });
    process.exitCode = 1; return;
  }

  let gate3ChannelDead = null;
  try {
    const pingOpts = gate3PingOptionsFromEnv(process.env);
    await runGate3Ping({
      ledger: seatingLedger,
      driver: seating.gate3DriverName,
      runAgent: trioRunAgent,
      timeoutMs: pingOpts.timeoutMs,
      attempts: pingOpts.attempts,
    });
  } catch (err) {
    gate3ChannelDead = {
      driver: seating.gate3DriverName,
      reason: String(err?.message || err).slice(0, 200),
    };
    process.stderr.write(`superjump-run: gate-3 channel DEAD after retries — generating anyway; ideas will be UNJUDGED, never survivors.\n`);
  }

  const outputPath = opts.output || join(skillDir(), 'journal', 'runs', `${started.replace(/[:.]/g, '-')}-${randomUUID()}.json`);
  try {
    const result = await runSuperjump(problem, {
      candidates: opts.candidates,
      runAgent: trioRunAgent,
      seatingLedger,
      seating,
      outputPath,
      controlPath: opts.control,
      timeoutMs,
      codingEffort: opts.effort === 'highest' ? 'highest' : 'auto',
      reviewEffort: 'highest',
      expectations: loadExpectations(),
      gate3ChannelDead,
    });
    writeFileSync(outputPath.replace(/\.json$/i, '.md'), renderReport(result));
    writeRunRecord({
      skill: 'superjump', tier: `superjump-${opts.candidates}`, started,
      ended: new Date().toISOString(), input: opts.input || '(--problem argv)',
      params: { candidates: opts.candidates, effort: opts.effort, timeoutMs },
      output: outputPath, result: result.status,
      cross_model: result.cross_model, duration_s: result.totalS,
    }, { skillDir: skillDir(), file: recordFile });
    process.stdout.write(JSON.stringify({ status: result.status, order: result.order, output: outputPath }, null, 2) + '\n');
    if (result.status !== 'complete' && result.status !== 'killed') process.exitCode = 1;
  } catch (err) {
    const partial = err?.superjumpPartial || err?.jumperPartial;
    if (partial && opts.output) writeFileSync(opts.output, JSON.stringify(partial, null, 2));
    process.stderr.write(`superjump-run: ${err?.name || 'Error'}: ${err?.message || err}\n`);
    process.exitCode = err instanceof JumperSelfReviewHalt || err instanceof JumperCrossFamilyDegradeHalt ? 1 : 1;
  }
}

const isMain = process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
if (isMain) main();
export { parseArgs, USAGE };

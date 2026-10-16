#!/usr/bin/env node
// bin/deal-chain.mjs — THE THIN CHAIN (2026-08-25, John-ratified: decision #4 "thin").
//
// One command makes "nothing ships without approval of the vetted model" REAL:
//
//   evaluate → tie-out → report → adversarial review (tie-out record AS INPUT) → HALT for John
//
//   node bin/deal-chain.mjs --deal <deal.py> --report <report.md> [--rounds 3] [--live] [--out <dir>]
//
// The deal script contract (3 lines to add to any deal model — SKILL.md shows the snippet):
// invoked as `python <deal.py> --chain-json`, it prints ONE JSON object:
//   { "tie_out": <agent.tie_out() result>, "values": <agent.evaluate()>, "inputs": {...} }
//
// The chain is fail-closed at every link: a failing tie-out BLOCKS before any model seat is
// paid; the review runs with --require-tie-out so a GO is IMPOSSIBLE without a passing
// tie-out record; the verdict is at most "GO — awaiting human ack" — John's sign-off is the
// real gate, and the RECEIPT (report hash · grounding · tie-out state) must ride in the
// deliverable footer. Exit 0 ONLY on GO/UNREVIEWED-with-gates-passed.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

import { runDealReview } from './deal-review.mjs';

function argOf(argv, name) { const i = argv.indexOf(name); return i >= 0 && i + 1 < argv.length ? argv[i + 1] : null; }
const log = (m) => process.stderr.write(`${m}\n`);

async function main() {
  const argv = process.argv.slice(2);
  const dealPath = argOf(argv, '--deal');
  const reportPath = argOf(argv, '--report');
  if (!dealPath || !reportPath) {
    console.error('usage: node bin/deal-chain.mjs --deal <deal.py> --report <report.md> [--rounds 3] [--live] [--out <dir>]');
    process.exit(2);
  }
  const outDir = argOf(argv, '--out') || path.join(path.dirname(path.resolve(reportPath)), 'deal-chain-out');

  // ---- 1+2. evaluate + tie-out (Python, exact-Decimal core — the ONLY math path) ----------
  log(`deal-chain 1/4: evaluate + tie-out — python ${dealPath} --chain-json`);
  const py = spawnSync(process.platform === 'win32' ? 'python' : 'python3', [dealPath, '--chain-json'], {
    encoding: 'utf8', cwd: path.dirname(path.resolve(dealPath)), timeout: 300000,
  });
  if (py.status !== 0) {
    log(`deal-chain BLOCKED at tie-out: the deal script exited ${py.status}.`);
    log(String(py.stderr || '').slice(-1500));
    process.exit(1);
  }
  let chainJson;
  try {
    // Review fix: parse the LAST parseable {...} block, not slice-from-first-brace —
    // a deal script that prints a brace-bearing progress line first must not break it.
    const raw = String(py.stdout || '');
    const starts = [];
    for (let i = raw.indexOf('{'); i !== -1; i = raw.indexOf('{', i + 1)) starts.push(i);
    let parsed = null;
    for (let k = starts.length - 1; k >= 0 && parsed === null; k--) {
      try { parsed = JSON.parse(raw.slice(starts[k])); } catch { /* try the previous { */ }
    }
    if (parsed === null) throw new Error('no parseable JSON object found in output');
    chainJson = parsed;
  } catch (e) {
    log(`deal-chain BLOCKED: the deal script's --chain-json output was not parseable JSON (${e.message}). The contract: print ONE object {tie_out, values, inputs} (LAST on stdout).`);
    process.exit(1);
  }
  const tieOut = chainJson.tie_out ?? null;
  if (!tieOut || tieOut.ok !== true) {
    log(`deal-chain BLOCKED at tie-out: ${tieOut ? `record present but ok!==true (${JSON.stringify(tieOut).slice(0, 300)})` : 'no tie_out in the chain output'} — no model seat was paid; fix the model first.`);
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'TIE-OUT.json'), JSON.stringify(tieOut ?? { ok: false, reason: 'missing' }, null, 2) + '\n', 'utf8');
    process.exit(1);
  }
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'TIE-OUT.json'), JSON.stringify(tieOut, null, 2) + '\n', 'utf8');
  log(`deal-chain: tie-out VERIFIED — ${tieOut.line ?? `${tieOut.nodes_compared} nodes, max delta ${tieOut.max_delta}`}`);

  // ---- 3+4. report → adversarial review, tie-out record AS INPUT --------------------------
  log('deal-chain 2/4: report → deal-review (tie-out record crosses the seam; --require-tie-out)');
  const rec = await runDealReview({
    reportText: fs.readFileSync(reportPath, 'utf8'),
    nodeValues: chainJson.values ?? {},
    declaredInputs: chainJson.inputs ?? {},
    rounds: Number(argOf(argv, '--rounds')) || 3,
    live: argv.includes('--live'),
    outDir,
    tieOut,
    requireTieOut: true,
    log,
  });

  // ---- 5. HALT for John — the machine never ships a model ---------------------------------
  const ok = rec.verdict.startsWith('GO') || rec.verdict.startsWith('UNREVIEWED');
  log('deal-chain 4/4: HALT for sign-off.');
  log(ok
    ? `Your call: the model tied out and the review ${rec.status === 'REVIEWED' ? 'ran dry' : 'gates passed (adversarial round not run — add --live for seats)'} — approve to ship? The receipt line above goes in the deliverable footer. Approve, or tell me what to change.`
    : `BLOCKED — do not ship: ${rec.verdict}. Findings and receipt are in ${outDir}.`);
  process.exit(ok ? 0 : 1);
}

main().catch((err) => { console.error(`deal-chain: ${err?.message ?? err}`); process.exit(1); });

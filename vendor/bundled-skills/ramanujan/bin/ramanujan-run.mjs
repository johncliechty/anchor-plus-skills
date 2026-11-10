#!/usr/bin/env node
// bin/ramanujan-run.mjs — the THIN CLI (P2 2026-07-25, journal-hardening review §4).
//
// Why this exists: a 16.7k-line engine reached 2026-07 with ZERO real runs because the
// only documented invocation was "hand-build the typed request (claims + ASTs per
// src/firewall-grammar.mjs) and run orchestrate() via node" — an AST-construction tax
// the SKILL.md itself calls a "tax". No entry point ⇒ no runs ⇒ no journal ⇒ the
// construction freeze (which requires journal evidence to lift) could never be lifted.
// This CLI removes the tax for exactly the slice the certifier engine can honestly
// settle — LITERAL FINITE ARITHMETIC — and captures every real run to journal/runs/.
//
// Honesty posture (NS3, locked v3): arithmetic claims are parsed into the firewall
// grammar and routed through the REAL VERIFY pillar (generator-independent checker —
// never the drafter's own word). Claim text this parser cannot turn into grammar is
// still routed, as a proof-bearing claim the engine will honestly refuse to settle.
// Nothing here self-assigns a rung.
//
// Usage:
//   node bin/ramanujan-run.mjs --claim "12*37+9 = 453" [--claim "1/3 + 1/6 = 1/2"]
//   node bin/ramanujan-run.mjs --input claims.json [--output out.json] [--depth FULL]
//     claims.json: [{ id?, statement, expr? }] (expr in firewall-grammar AST form)

import { readFileSync, writeFileSync, mkdirSync, realpathSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import process from 'node:process';

import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';

import { orchestrate, PILLAR } from '../src/orchestrator.mjs';
import { ClaimLedger } from '../src/claim-ledger.mjs';
import { int, rational, neg, add, sub, mul, div } from '../src/firewall-grammar.mjs';
import { AdjudicationDispatcher, DurableNonceStore, loadDurabilitySubstrate } from '../src/adjudication.mjs';
import { makeDispatchCapability } from '../src/dispatch-capability.mjs';
import { runSubprocess } from '../src/firewall-subprocess.mjs';

const USAGE =
  'usage: node bin/ramanujan-run.mjs --claim "<arith expr> = <value>" [--claim ...]\n' +
  '       node bin/ramanujan-run.mjs --input <claims.json> [--output <file>] [--depth LITE|SPIKE|FULL]\n' +
  '       (arithmetic claims are certified through the VERIFY pillar; anything the\n' +
  '        parser cannot express in the firewall grammar routes as proof-bearing and\n' +
  '        is honestly left unsettled — never asserted)';

// ── A tiny exact-arithmetic parser → firewall-grammar AST ────────────────────
// Grammar: expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ;
// factor := '-' factor | '(' expr ')' | INT . Division builds the exact DIV node.
export function parseArith(text) {
  const s = String(text);
  let i = 0;
  const ws = () => { while (i < s.length && /\s/.test(s[i])) i++; };
  const fail = (why) => { throw new Error(`not grammar arithmetic (${why}) at offset ${i}: ${JSON.stringify(s)}`); };
  function factor() {
    ws();
    if (s[i] === '-') { i++; return neg(factor()); }
    if (s[i] === '(') {
      i++;
      const e = expr();
      ws();
      if (s[i] !== ')') fail('missing )');
      i++;
      return e;
    }
    const m = /^\d+/.exec(s.slice(i));
    if (!m) fail('expected integer');
    i += m[0].length;
    return int(BigInt(m[0]));
  }
  function term() {
    let left = factor();
    for (;;) {
      ws();
      if (s[i] === '*') { i++; left = mul(left, factor()); }
      else if (s[i] === '/') { i++; left = div(left, factor()); }
      else return left;
    }
  }
  function expr() {
    let left = term();
    for (;;) {
      ws();
      if (s[i] === '+') { i++; left = add(left, term()); }
      else if (s[i] === '-' && s[i + 1] !== '-') { i++; left = sub(left, term()); }
      else return left;
    }
  }
  const e = expr();
  ws();
  if (i !== s.length) fail('trailing input');
  return e;
}

/** "LHS = RHS" → a computational claim with expr sub(LHS,RHS) (holds iff it evaluates to 0)
 *  — or, when either side refuses the grammar, an honest proof-bearing claim (no expr). */
export function claimFromText(text, n) {
  const id = `cli::c${n}`;
  const m = String(text).split('=');
  if (m.length === 2) {
    try {
      const lhs = parseArith(m[0]);
      const rhs = parseArith(m[1]);
      return {
        id,
        type: 'computational',
        statement: String(text).trim(),
        expr: sub(lhs, rhs), // claim holds ⇔ exact evaluation is 0
        _cli: { route: 'grammar-arithmetic', holds_iff: 'expr evaluates exactly to 0' },
      };
    } catch { /* fall through to the honest non-grammar route */ }
  }
  return {
    id,
    type: 'proof-bearing',
    statement: String(text).trim(),
    _cli: { route: 'non-grammar', note: 'not expressible as literal finite arithmetic — the engine will not settle this' },
  };
}

export function parseArgs(argv) {
  const o = { claims: [], input: null, output: null, depth: 'FULL', help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--claim') { const v = argv[++i]; if (!v) throw new Error('--claim requires text'); o.claims.push(v); }
    else if (a === '--input') { o.input = argv[++i]; if (!o.input) throw new Error('--input requires a file'); }
    else if (a === '--output') { o.output = argv[++i]; if (!o.output) throw new Error('--output requires a file'); }
    else if (a === '--depth') { o.depth = argv[++i]; if (!o.depth) throw new Error('--depth requires LITE|SPIKE|FULL'); }
    else if (a === '--help' || a === '-h') { o.help = true; }
    else throw new Error(`unknown argument ${JSON.stringify(a)}`);
  }
  return o;
}

/** Run capture (Skill Foundry AGENTS.md "Run capture"). Best-effort; skipped under tests. */
export function writeRunRecord(record, { skillDir = resolve(dirname(fileURLToPath(import.meta.url)), '..') } = {}) {
  try {
    if (process.env.NODE_TEST_CONTEXT) return null;
    const dir = join(skillDir, 'journal', 'runs');
    mkdirSync(dir, { recursive: true });
    const started = record.started || new Date().toISOString();
    const file = join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`);
    writeFileSync(file, JSON.stringify({ skill: 'ramanujan', ...record }, null, 2) + '\n', 'utf8');
    return file;
  } catch {
    return null;
  }
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`ramanujan-run: ${err.message}\n${USAGE}\n`);
    process.exitCode = 2;
    return;
  }
  if (opts.help) { process.stdout.write(`${USAGE}\n`); return; }

  let claims;
  if (opts.input) {
    const raw = JSON.parse(readFileSync(opts.input, 'utf8'));
    if (!Array.isArray(raw) || !raw.length) {
      process.stderr.write('ramanujan-run: --input must be a non-empty JSON array of claims\n');
      process.exitCode = 2;
      return;
    }
    claims = raw.map((c, n) => (typeof c === 'string'
      ? claimFromText(c, n + 1)
      : { id: c.id || `cli::c${n + 1}`, type: c.expr ? 'computational' : (c.type || 'proof-bearing'), ...c }));
  } else if (opts.claims.length) {
    claims = opts.claims.map((t, n) => claimFromText(t, n + 1));
  } else {
    process.stderr.write(`ramanujan-run: nothing to verify\n${USAGE}\n`);
    process.exitCode = 2;
    return;
  }

  const started = new Date().toISOString();
  const t0 = Date.now();

  // Arm the REAL firewall-subprocess certifier: durable single-use nonce store (the
  // inherited foreman-lib substrate) + the real re-executable subprocess mint. This is
  // the gated-dispatch capability — the ONLY thing it can settle is the in-grammar
  // arithmetic class (the Honesty Law keeps proof/conceptual claims unsettled even
  // with the gate open). If the substrate cannot load (stranger machine, missing
  // manifest), the run proceeds UNARMED and says so — claims honestly ABSTAIN.
  // Ship-safe substrate resolution (2026-07-26): the inherits manifest's relative
  // foreman-lib path does not resolve in the collaborator bundle (foreman is a
  // SIBLING there: bundled-skills/foreman). Probe env → sibling → canonical → manifest.
  async function loadSubstrateShipSafe() {
    const here = dirname(fileURLToPath(import.meta.url)); // <skill>/bin
    const cands = [
      process.env.ANCHOR_TRIO_DIR && join(process.env.ANCHOR_TRIO_DIR, 'foreman', 'bin', 'foreman-lib.mjs'),
      resolve(here, '..', '..', 'foreman', 'bin', 'foreman-lib.mjs'), // vendored sibling layout
      '<path>',                      // author-host canonical
    ].filter(Boolean);
    for (const c of cands) {
      if (existsSync(c)) {
        const ns = await import(pathToFileURL(c).href);
        if (['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint'].every((f) => typeof ns[f] === 'function')) return ns;
      }
    }
    return loadDurabilitySubstrate(); // manifest fallback (canonical dev layout)
  }

  let capability = null;
  let armNote = null;
  try {
    const substrate = await loadSubstrateShipSafe();
    const stateDir = mkdtempSync(join(tmpdir(), 'ramanujan-run-'));
    const store = DurableNonceStore.load(substrate, join(stateDir, 'nonce.checkpoint.json'));
    const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });
    capability = makeDispatchCapability({ dispatcher }); // default mint = the real subprocess
  } catch (err) {
    armNote = `certifier NOT armed (${String(err?.message ?? err).slice(0, 160)}) — computational claims will honestly ABSTAIN`;
    process.stderr.write(`ramanujan-run: ${armNote}\n`);
  }

  let result;
  try {
    result = orchestrate(
      { pillar: PILLAR.VERIFY, claims },
      { ledger: new ClaimLedger(), ...(capability ? { capability } : {}), depth: opts.depth, env: process.env },
    );
  } catch (err) {
    process.stderr.write(`ramanujan-run: HALT — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`);
    writeRunRecord({
      tier: 'halted', started, ended: new Date().toISOString(),
      input: opts.input || '(--claim argv)', params: { depth: opts.depth, claims: claims.length },
      output: null, result: `HALT: ${err?.name ?? 'Error'}`, cross_model: false, models: null,
      duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
    });
    process.exitCode = 1;
    return;
  }

  // THE READ-OFF LAYER (honesty-critical): the engine's VERIFIED/OBSERVED certifies the
  // COMPUTATION (a re-executable artifact reproduced the exact value) — it does NOT
  // assert the equation is TRUE. "2+2=5" computes reproducibly to -1: computation
  // certified, equation REFUTED. The CLI derives equation_holds by RE-EXECUTING the
  // same firewall subprocess (that re-executability is the design's whole point) and
  // mechanically comparing the exact rational result to zero — no model math anywhere.
  const routed = result?.output?.results ?? [];
  const summary = claims.map((c) => {
    const r = routed.find((x) => x.claim_id === c.id) ?? null;
    const s = {
      id: c.id,
      statement: c.statement,
      engine_verdict: r?.verdict ?? null,
      rung: r?.rung ?? null,
    };
    if (c.type === 'computational' && c.expr && r?.settled) {
      try {
        const run = runSubprocess(c.expr);
        const val = JSON.parse(run.stdout).result; // exact rational {num, den}
        s.exact_value = `${val.num}${val.den === '1' ? '' : `/${val.den}`}`;
        s.equation_holds = val.num === '0';
        s.verdict = s.equation_holds
          ? 'HOLDS (certified by exact re-executable arithmetic)'
          : `REFUTED (certified exact value of LHS-RHS is ${s.exact_value}, not 0)`;
      } catch (err) {
        s.verdict = `UNSETTLED (re-execution failed: ${String(err?.message ?? err).slice(0, 120)})`;
      }
    } else {
      s.verdict = 'UNSETTLED (outside the certifier envelope — honestly not asserted)';
    }
    return s;
  });
  for (const s of summary) process.stderr.write(`ramanujan-run: ${s.id} · ${s.verdict}\n`);

  const out = {
    summary,
    claims, result, depth: opts.depth,
    certifierArmed: capability != null,
    armNote: armNote ?? undefined,
    bandCertifierKnob: result?.certifierArmed ?? null,
  };
  const serialized = `${JSON.stringify(out, (_k, v) => (typeof v === 'bigint' ? v.toString() : v), 2)}\n`;
  if (opts.output) writeFileSync(opts.output, serialized, 'utf8');
  else process.stdout.write(serialized);

  writeRunRecord({
    tier: `verify-${String(opts.depth).toLowerCase()}`,
    started, ended: new Date().toISOString(),
    input: opts.input || '(--claim argv)',
    params: { depth: opts.depth, claims: claims.length, grammarClaims: claims.filter((c) => c.type === 'computational').length },
    output: opts.output || '(stdout)',
    result: `verified through the VERIFY pillar (certifierArmed=${out.certifierArmed})`,
    cross_model: false, // single-process deterministic verify — never claim otherwise
    models: null,
    duration_s: Math.round((Date.now() - t0) / 1000),
    journal_ref: null,
  });
}

// realpath + case-fold both sides (the gandalf/jumper junction-no-op fix, applied from birth).
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    const canon = (p) => {
      const abs = resolve(p);
      let real = abs;
      try { real = realpathSync(abs); } catch { /* keep abs */ }
      return process.platform === 'win32' ? real.toLowerCase() : real;
    };
    return canon(fileURLToPath(import.meta.url)) === canon(entry);
  } catch { return false; }
}
if (invokedDirectly()) {
  main().catch((err) => {
    process.stderr.write(`ramanujan-run: fatal — ${err?.message ?? err}\n`);
    process.exitCode = 1;
  });
}

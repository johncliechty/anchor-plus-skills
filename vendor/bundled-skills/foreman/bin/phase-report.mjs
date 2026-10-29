#!/usr/bin/env node
// phase-report.mjs — SPIKE(foreman-parallel): aggregate Foreman's per-call + gate
// wall-clock/token records into a PER-PHASE, PER-WAVE breakdown.
//
// WHY: Foreman records per-call telemetry (transport.mjs makeTelemetryRecord) and
// the orchestrator runs the gate, but nothing aggregates them — the dashboard's
// elapsed/token% are null, so "where does a wave's wall-clock go?" was unanswerable.
// The instrumentation sinks (run-live.mjs per-call + wave-engine.mjs runGate) append
// JSONL records to <project>/.foreman/phase-timings.jsonl; this script interprets them.
//
// The call LABELS already encode the phase + wave:
//   execute:wN        fix:wN.j        review:wN#i (and #i#retry)        gate:wN.j
//
// USAGE:
//   node bin/phase-report.mjs <phase-timings.jsonl> [--compare <variant.jsonl>] [--json]
//
// --compare runs the A/B: baseline (serial reviewers) vs variant (concurrent), and
// prints the delta on review-phase wall-clock + total. PURE + deterministic (no model
// call) so it is unit-testable; the CLI at the bottom only does file IO + printing.

import fs from 'node:fs';

// ---------------------------------------------------------------------------
// Pure core (unit-tested).
// ---------------------------------------------------------------------------

const PHASES = ['execute', 'review', 'fix', 'gate'];

/** Parse a Foreman call/gate label into {phase, wave, sub}. Unknown ⇒ phase:null. */
export function parseLabel(label) {
  if (typeof label !== 'string') return { phase: null, wave: null, sub: null };
  let m;
  if ((m = label.match(/^execute:w(\d+)/))) return { phase: 'execute', wave: +m[1], sub: null };
  if ((m = label.match(/^review:w(\d+)#(\d+)/))) return { phase: 'review', wave: +m[1], sub: +m[2] };
  if ((m = label.match(/^fix:w(\d+)\.(\d+)/))) return { phase: 'fix', wave: +m[1], sub: +m[2] };
  if ((m = label.match(/^gate:w(\d+)\.(\d+)/))) return { phase: 'gate', wave: +m[1], sub: +m[2] };
  return { phase: null, wave: null, sub: null };
}

/** Parse a JSONL string into an array of records (skips blank/unparseable lines). */
export function parseJsonl(text) {
  const out = [];
  for (const line of String(text).split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try { out.push(JSON.parse(t)); } catch { /* skip a torn line, never crash */ }
  }
  return out;
}

/**
 * Aggregate records into per-phase + per-wave sums, mean fix-iterations k, and the
 * per-phase share of total wall-clock. Each record needs {label, duration_ms,
 * output_tokens}. A `#retry` review call folds into its review phase.
 */
export function aggregate(records) {
  const byPhase = Object.fromEntries(PHASES.map((p) => [p, { ms: 0, tokens: 0, calls: 0 }]));
  const waves = new Map(); // wave -> {execute,review,fix,gate}{ms,tokens,calls} + fixIters Set
  let unattributed = 0;

  for (const r of records) {
    if (r && r.kind === 'phase') continue;   // S1 wall-clock phase records: summed by phaseWalls, never twice here
    const { phase, wave, sub } = parseLabel(r.label);
    if (!phase) { unattributed++; continue; }
    const ms = Number(r.duration_ms) || 0;
    const tok = Number(r.output_tokens) || 0;
    byPhase[phase].ms += ms; byPhase[phase].tokens += tok; byPhase[phase].calls += 1;
    if (!waves.has(wave)) {
      waves.set(wave, { wave, execute: blank(), review: blank(), fix: blank(), gate: blank(), fixIters: new Set() });
    }
    const w = waves.get(wave);
    w[phase].ms += ms; w[phase].tokens += tok; w[phase].calls += 1;
    if (phase === 'fix' && sub != null) w.fixIters.add(sub);
  }

  const totalMs = PHASES.reduce((a, p) => a + byPhase[p].ms, 0);
  const totalTok = PHASES.reduce((a, p) => a + byPhase[p].tokens, 0);
  const phaseShare = Object.fromEntries(PHASES.map((p) =>
    [p, totalMs > 0 ? byPhase[p].ms / totalMs : 0]));

  const waveList = [...waves.values()].sort((a, b) => a.wave - b.wave)
    .map((w) => ({ ...w, fixIters: w.fixIters.size }));
  const meanK = waveList.length
    ? waveList.reduce((a, w) => a + w.fixIters, 0) / waveList.length : 0;

  // Mean per-review-call ms — the unit that concurrent reviewers overlaps away.
  const meanReviewCallMs = byPhase.review.calls ? byPhase.review.ms / byPhase.review.calls : 0;
  const meanGateMs = byPhase.gate.calls ? byPhase.gate.ms / byPhase.gate.calls : 0;

  return {
    byPhase, phaseShare, totalMs, totalTok, meanK,
    meanReviewCallMs, meanGateMs, waves: waveList,
    waveCount: waveList.length, unattributed,
  };
}

function blank() { return { ms: 0, tokens: 0, calls: 0 }; }

/** Every phase's own wall clock incl. elegance and land (S1, 2026-10-10): the engine's {kind:'phase'} records (the
 * gate's own {kind:'gate'} record times the same run the 'gate' phase record does, so it is not added again),
 * optionally only those at or after `sinceTs` (one run). Pure. */
export const WALL_PHASES = ['execute', 'gate', 'review', 'fix', 'elegance', 'land'];
export function phaseWalls(records, sinceTs = 0) {
  const out = Object.fromEntries(WALL_PHASES.map((p) => [p, 0]));
  for (const r of records || []) {
    if (!r || r.kind !== 'phase') continue;
    if (sinceTs && Number(r.ts) < sinceTs) continue;
    const p = String(r.phase || '');
    out[p] = (out[p] || 0) + (Number(r.duration_ms) || 0);
  }
  const total = Object.values(out).reduce((a, b) => a + b, 0);
  return { ms: out, total_ms: total, share: Object.fromEntries(Object.entries(out).map(([k, v]) => [k, total ? +(v / total).toFixed(3) : 0])) };
}

/**
 * Estimate the wall-clock a wave's REVIEW phase would take SERIAL vs CONCURRENT,
 * from a serial-baseline aggregate. Serial review wall-clock = sum of review calls;
 * concurrent (per round) ≈ the slowest reviewer in the round. With reviewerCount R
 * and the same per-call mean, the saved fraction of review wall-clock ≈ (R-1)/R.
 * This is the MODEL estimate; the real number comes from an actual --compare A/B run.
 */
export function reviewConcurrencyModel(agg, reviewerCount = 2) {
  const serialMs = agg.byPhase.review.ms;
  const rounds = reviewerCount > 0 ? agg.byPhase.review.calls / reviewerCount : 0;
  const concurrentMs = rounds * agg.meanReviewCallMs; // ~1 reviewer per round
  const savedMs = serialMs - concurrentMs;
  return {
    reviewerCount, serialReviewMs: serialMs, estConcurrentReviewMs: concurrentMs,
    estSavedMs: savedMs,
    estSavedShareOfTotal: agg.totalMs > 0 ? savedMs / agg.totalMs : 0,
  };
}

/** A/B delta between a baseline (serial) and a variant (concurrent) aggregate. */
export function compareRuns(baseline, variant) {
  return {
    review: {
      baselineMs: baseline.byPhase.review.ms,
      variantMs: variant.byPhase.review.ms,
      deltaMs: baseline.byPhase.review.ms - variant.byPhase.review.ms,
    },
    total: {
      baselineMs: baseline.totalMs, variantMs: variant.totalMs,
      deltaMs: baseline.totalMs - variant.totalMs,
      speedup: variant.totalMs > 0 ? baseline.totalMs / variant.totalMs : null,
    },
    tokens: { baseline: baseline.totalTok, variant: variant.totalTok },
  };
}

const fmtMs = (ms) => ms >= 60000 ? `${(ms / 60000).toFixed(1)}m` : `${(ms / 1000).toFixed(1)}s`;
const pct = (x) => `${(x * 100).toFixed(1)}%`;

/** Render a human-readable report from an aggregate. */
export function renderReport(agg, { title = 'Foreman phase breakdown' } = {}) {
  const L = [];
  L.push(`# ${title}`);
  L.push(`waves=${agg.waveCount} · total wall-clock=${fmtMs(agg.totalMs)} · total out-tokens=${agg.totalTok} · mean fix-iters k=${agg.meanK.toFixed(2)}`);
  if (agg.unattributed) L.push(`(note: ${agg.unattributed} record(s) had an unrecognized label — excluded)`);
  L.push('');
  L.push(`phase     wall-clock   share    out-tokens   calls`);
  for (const p of PHASES) {
    const b = agg.byPhase[p];
    L.push(`${p.padEnd(9)} ${fmtMs(b.ms).padStart(10)} ${pct(agg.phaseShare[p]).padStart(7)} ${String(b.tokens).padStart(11)} ${String(b.calls).padStart(7)}`);
  }
  L.push('');
  L.push(`mean per review call: ${fmtMs(agg.meanReviewCallMs)} · mean gate run: ${fmtMs(agg.meanGateMs)}`);
  const model = reviewConcurrencyModel(agg);
  L.push(`MODEL estimate — concurrent reviewers would save ~${fmtMs(model.estSavedMs)} (${pct(model.estSavedShareOfTotal)} of total). Confirm with a --compare A/B run.`);
  return L.join('\n');
}

// ---------------------------------------------------------------------------
// CLI (file IO + printing only).
// ---------------------------------------------------------------------------

function isMain() {
  try { return import.meta.url === new URL(`file://${process.argv[1]}`).href
    || import.meta.url.endsWith(process.argv[1]?.replace(/\\/g, '/') || ' '); }
  catch { return false; }
}

if (isMain()) {
  const argv = process.argv.slice(2);
  const wantJson = argv.includes('--json');
  const ci = argv.indexOf('--compare');
  const comparePath = ci >= 0 ? argv[ci + 1] : null;
  const file = argv.find((a) => !a.startsWith('--') && a !== comparePath);
  if (!file) {
    process.stderr.write('usage: node bin/phase-report.mjs <phase-timings.jsonl> [--compare <variant.jsonl>] [--json]\n');
    process.exit(2);
  }
  const base = aggregate(parseJsonl(fs.readFileSync(file, 'utf8')));
  if (comparePath) {
    const variant = aggregate(parseJsonl(fs.readFileSync(comparePath, 'utf8')));
    const cmp = compareRuns(base, variant);
    if (wantJson) { console.log(JSON.stringify({ baseline: base, variant, compare: cmp }, null, 2)); }
    else {
      console.log(renderReport(base, { title: 'BASELINE (serial reviewers)' }));
      console.log('\n' + renderReport(variant, { title: 'VARIANT (concurrent reviewers)' }));
      console.log(`\n# A/B DELTA`);
      console.log(`review wall-clock: ${fmtMs(cmp.review.baselineMs)} → ${fmtMs(cmp.review.variantMs)} (saved ${fmtMs(cmp.review.deltaMs)})`);
      console.log(`total wall-clock:  ${fmtMs(cmp.total.baselineMs)} → ${fmtMs(cmp.total.variantMs)} (saved ${fmtMs(cmp.total.deltaMs)}; speedup ${cmp.total.speedup ? cmp.total.speedup.toFixed(2) + '×' : 'n/a'})`);
      console.log(`out-tokens:        ${cmp.tokens.baseline} → ${cmp.tokens.variant} (concurrency does NOT reduce tokens — both reviewers still run)`);
    }
  } else {
    console.log(wantJson ? JSON.stringify(base, null, 2) : renderReport(base));
  }
}

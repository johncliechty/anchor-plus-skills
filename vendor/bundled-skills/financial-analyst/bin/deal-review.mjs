#!/usr/bin/env node
// bin/deal-review.mjs — financial-analyst's ADVERSARIAL REVIEW ENGINE (2026-07-25,
// prose-lock=C amendment in planning/portfolio-program/PORTFOLIO-RIGHTSIZE-2026-07.md).
//
// Before this file, the skill's review layer did not exist in ANY form — SKILL.md
// claimed "ALWAYS true cross-model" with zero seats, and tie_out() (Excel==Python)
// was the only check: compiler self-consistency, blind to wrong assumptions. This
// engine attaches STRICTLY DOWNSTREAM of the calc engine — it consumes the report +
// the evaluated node values and NEVER re-derives math, never touches graph_engine.py
// or the compilers (the calc engine is fenced KEEP).
//
// Doctrine: one canonical copy, consumers import. All consensus/judge machinery is
// the trio's — nothing here forks it:
//   - Sharks + ≥2-agree BLOCKER tally: crucible/bin/shark-tank.mjs (runSharkTank)
//   - Context-free judge (cross-family selected): crucible/bin/judge.mjs (makeJudge)
//   - Live seats + UNFORGEABLE cross_model stamp: researchPrime/bin/live-round-agent.mjs
//   - The financial rubric: crucible loadPack('investment-memo') — c2 is verbatim the
//     grounding rule SKILL.md previously only asked for politely.
// What IS new here (the domain layer): the deterministic GROUNDING GATE — every
// significant number in the report must trace to the evaluated node dict or the
// declared inputs — plus the template-omissions criterion (SKILL.md's own honesty
// note about textbook-granularity templates, now reviewer-enforced).
//
// Usage:
//   node bin/deal-review.mjs --report <report.md> --values <nodes.json>
//        [--inputs <inputs.json>] [--rounds 3] [--live] [--out <dir>]
//   nodes.json: the dict from FinancialAnalystAgent.evaluate() (name -> value)
//   Without --live and without an injected agent: HONEST STOP (nothing fabricated).

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import process from 'node:process';

const TRIO = resolveTrioRoot();
const trioUrl = (rel) => pathToFileURL(path.join(TRIO, rel)).href;

/** Ship-safe trio-root resolution (2026-07-26): (1) ANCHOR_TRIO_DIR env, (2) the
 *  BUNDLED sibling layout (vendor/bundled-skills/<skill>/bin -> ../../ holds
 *  crucible/researchPrime/drivers on a collaborator machine), (3) the author-host
 *  canonical path. Same probe order as the crucible foundry-triage resolver. */
function resolveTrioRoot() {
  if (process.env.ANCHOR_TRIO_DIR) return process.env.ANCHOR_TRIO_DIR;
  const here = path.dirname(fileURLToPath(import.meta.url)); // <skill>/bin
  const sibling = path.resolve(here, '..', '..');
  if (fs.existsSync(path.join(sibling, 'crucible', 'bin', 'shark-tank.mjs'))) return sibling;
  return '<path>';
}

// ── The deterministic grounding gate (pure; exported for tests) ──────────────

/** Normalize a number token to a canonical decimal string family (for matching). */
export function normalizeNumber(tok) {
  const cleaned = String(tok).replace(/[$,%\s,]/g, '').replace(/[()]/g, '');
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

/** Extract the SIGNIFICANT number tokens of a report (the ones that must be grounded).
 *  Skips years (1900-2100 bare integers), enumerators (bare 0-30), and percentages of
 *  the form "x%"? No — percents are claims too. Skips section refs like "3." headers. */
export function extractSignificantNumbers(text) {
  const out = [];
  const re = /\$?\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?%?|\$?\(?-?\d+\.\d+\)?%?|\$\(?-?\d+\)?%?|(?<![\w.])\(?-?\d{4,}\)?%?(?![\w.])|(?<![\w.$])\d+(?:\.\d+)?%(?![\w])/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const tok = m[0];
    const val = normalizeNumber(tok);
    if (val == null) continue;
    // Bare 4-digit integers in the year range with no $/%/decimal are treated as years.
    if (/^\d{4}$/.test(tok) && val >= 1900 && val <= 2100) continue;
    out.push({ token: tok, value: val, index: m.index });
  }
  return out;
}

/** True iff `value` matches any grounded value under exact/rounding tolerance. */
function matchesGrounded(value, groundedValues) {
  for (const g of groundedValues) {
    if (!Number.isFinite(g)) continue;
    if (g === value) return true;
    // Reports round: accept a report token that is the node value rounded to 0-4 dp,
    // in thousands/millions (x/1e3, x/1e6), or as a percent rendering (x*100).
    for (const scaled of [g, g / 1e3, g / 1e6, g * 100]) {
      for (let dp = 0; dp <= 4; dp++) {
        const f = Math.pow(10, dp);
        if (Math.round(scaled * f) / f === value) return true;
      }
    }
  }
  return false;
}

/**
 * The gate: every significant number in the report ∈ evaluated nodes ∪ declared inputs.
 * Returns { ok, checked, violations: [{token, value, index, context}] }.
 */
export function checkGrounding(reportText, nodeValues = {}, declaredInputs = {}) {
  const grounded = [];
  for (const src of [nodeValues, declaredInputs]) {
    for (const v of Object.values(src ?? {})) {
      const n = typeof v === 'number' ? v : normalizeNumber(v);
      if (n != null) grounded.push(n);
    }
  }
  const nums = extractSignificantNumbers(String(reportText));
  const violations = nums
    .filter((t) => !matchesGrounded(t.value, grounded))
    .map((t) => ({
      ...t,
      context: String(reportText).slice(Math.max(0, t.index - 60), t.index + t.token.length + 60).replace(/\s+/g, ' '),
    }));
  return { ok: violations.length === 0, checked: nums.length, violations };
}

// ── The charter (North Star for the review round) ────────────────────────────

export async function buildCharter() {
  const { loadPack } = await import(trioUrl('crucible/bin/packs/registry.mjs'));
  const pack = loadPack('investment-memo');
  const criteria = (pack?.rubric?.criteria ?? []).map((c) => `- [${c.id}] ${c.statement}`);
  return [
    'DEAL-REVIEW CHARTER (financial-analyst adversarial engine, 2026-07-25; tie-out premise',
    'made honest 2026-08-25). The artifact under review is a FINANCIAL DEAL REPORT produced',
    'by a deterministic exact-Decimal calculation engine. Whether the math tied out is',
    'CARRIED IN THE RECORD (tie_out.state) — never assumed; your job is everything the',
    'math cannot prove:',
    ...criteria,
    '- [fa1] TEMPLATE OMISSIONS: the shipped templates are textbook-granularity',
    '  (no option-pool shuffle, SAFEs, share counts, catch-up tiers, IRR/MOIC unless',
    '  extended). FLAG as BLOCKER any omission that is LOAD-BEARING for THIS deal and',
    '  was not extended or explicitly caveated in the report.',
    '- [fa2] ASSUMPTION SANITY: inputs the model treats as given (valuations, rates,',
    '  waterfalls) must be plausible and sourced for this deal, or caveated.',
    '- [fa3] GROUNDING: every number must trace to the evaluated graph or declared',
    '  inputs (a deterministic gate enforces this mechanically; flag semantic abuse',
    '  the gate cannot see — right number, wrong claim).',
    'A finding MUST set traces_to_north_star and name the criterion id it blocks.',
  ].join('\n');
}

// ── The engine ───────────────────────────────────────────────────────────────

/**
 * Run the review. `agent` is injectable (tests); absent agent + live:false ⇒ honest stop.
 * @returns {Promise<object>} the review record (also written to --out when given)
 */
export async function runDealReview({
  reportText,
  nodeValues = {},
  declaredInputs = {},
  rounds = 3,
  agent = null,
  live = false,
  outDir = null,
  // 2026-08-25 (John-ratified card): the tie-out record CROSSES the seam. The charter
  // asserted "tie-out proved Excel==Python" on faith; now it is an input. `tieOut` is the
  // record from agent_interface.tie_out(); `requireTieOut` (the chain sets it) makes a GO
  // impossible without a PASSING record. Without a record the verdict says UNVERIFIED.
  tieOut = null,
  requireTieOut = false,
  log = (m) => process.stderr.write(`${m}\n`),
} = {}) {
  if (typeof reportText !== 'string' || !reportText.trim()) {
    throw new Error('runDealReview requires the report text (the artifact under review)');
  }

  // 1. The deterministic grounding gate — runs BEFORE any paid seat.
  const grounding = checkGrounding(reportText, nodeValues, declaredInputs);
  log(`grounding gate: ${grounding.checked} number(s) checked · ${grounding.violations.length} ungrounded`);

  // 2. Seats: injected (tests) > live (prefs-aware cross-family) > honest stop.
  let tracker = null;
  let liveInfo = null;
  if (!agent && live) {
    const lra = await import(trioUrl('researchPrime/bin/live-round-agent.mjs'));
    tracker = lra.makeReachedFamilyTracker();
    agent = await lra.buildLiveRoundAgent({ tracker, env: process.env });
    liveInfo = 'live seats bound from coding/review family prefs';
    log(liveInfo);
  }
  if (!agent) {
    // The literature-review honest-stop pattern, verbatim in spirit: nothing was
    // reviewed; nothing is stamped reviewed; the grounding gate result still stands.
    const tieOutVerifiedGO = tieOut != null && tieOut.ok === true;
    const tieOutStateGO = tieOutVerifiedGO
      ? `VERIFIED (${tieOut.nodes_compared ?? '?'} nodes, max delta ${tieOut.max_delta ?? '?'})`
      : tieOut != null ? 'FAILED (record present, ok!==true)' : 'UNVERIFIED (no record crossed the seam)';
    const gatesPass = grounding.ok && (!requireTieOut || tieOutVerifiedGO);
    const record = {
      skill: 'financial-analyst', engine: 'deal-review', ts: new Date().toISOString(),
      status: 'STOPPED-HONESTLY',
      reason: 'no live model seats (--live) and no injected agent — the adversarial review did NOT run; nothing was fabricated',
      grounding,
      tie_out: { state: tieOutStateGO, verified: tieOutVerifiedGO, required: requireTieOut === true, record: tieOut ?? null },
      cross_model: false,
      verdict: gatesPass ? 'UNREVIEWED (deterministic gates PASSED; adversarial review not run)' :
        !grounding.ok ? 'BLOCKED (grounding gate FAILED; adversarial review not run)' :
        `BLOCKED (tie-out ${tieOutStateGO}; adversarial review not run)`,
    };
    record.receipt = buildReceipt(reportText, { nodeValues, declaredInputs, tieOutState: tieOutStateGO, grounding });
    if (outDir) writeRecord(outDir, record, log);
    log(`STOPPED HONESTLY: ${record.reason}`);
    log(`RECEIPT (required in the deliverable footer): ${record.receipt.footer_line}`);
    return record;
  }

  const { runSharkTank } = await import(trioUrl('crucible/bin/shark-tank.mjs'));
  const { makeJudge } = await import(trioUrl('crucible/bin/judge.mjs'));
  const northStar = await buildCharter();

  // 3. Convergence-until-dry over the ≥2-agree Shark tally (cap = rounds).
  const roundResults = [];
  const priorBlockerIds = [];
  let lastVerdict = null;
  for (let r = 1; r <= Math.max(1, rounds); r++) {
    const verdict = await runSharkTank({
      agent, northStar, draft: reportText, round: r,
      priorBlockerIds: [...priorBlockerIds], sharkRoles: 3, log,
    });
    roundResults.push({
      round: r, verdict: verdict.verdict, dry: verdict.dry, inconclusive: verdict.inconclusive,
      newBlockers: verdict.newBlockers.map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, message: b.message })),
      demoted: verdict.demoted.length,
    });
    for (const b of verdict.blockers) if (!priorBlockerIds.includes(b.id)) priorBlockerIds.push(b.id);
    lastVerdict = verdict;
    log(`round ${r}: ${verdict.verdict} · newBlockers=${verdict.newBlockers.length} · dry=${verdict.dry}`);
    if (verdict.dry && !verdict.inconclusive) break;
  }

  // 4. The context-free Judge (cross-family when routes allow).
  const judge = makeJudge({ agent, log });
  const judgeVerdict = await judge.decide({
    northStar, findings: lastVerdict?.findings ?? [], round: roundResults.length,
  });

  // 5. Honest stamps. cross_model is DERIVED from the tracker (unforgeable) — an
  // injected/test agent or single-family run is cross_model:false, plainly.
  const families = tracker ? tracker.families() : [];
  const cross_model = families.length > 1;
  const openBlockers = (lastVerdict?.blockers ?? []).map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, message: b.message }));
  const tieOutVerified = tieOut != null && tieOut.ok === true;
  const tieOutState = tieOutVerified
    ? `VERIFIED (${tieOut.nodes_compared ?? '?'} nodes, max delta ${tieOut.max_delta ?? '?'})`
    : tieOut != null ? 'FAILED (record present, ok!==true)' : 'UNVERIFIED (no record crossed the seam)';
  const pass = grounding.ok && (lastVerdict?.dry === true) && !lastVerdict?.inconclusive && judgeVerdict?.lockable === true
    && (!requireTieOut || tieOutVerified);
  const record = {
    skill: 'financial-analyst', engine: 'deal-review', ts: new Date().toISOString(),
    status: 'REVIEWED',
    grounding,
    tie_out: { state: tieOutState, verified: tieOutVerified, required: requireTieOut === true, record: tieOut ?? null },
    rounds: roundResults,
    openBlockers,
    judge: { decision: judgeVerdict?.decision ?? null, lockable: judgeVerdict?.lockable === true, stamp: judgeVerdict?.stamp ?? null },
    cross_model,
    substrate_families: families,
    single_family_note: cross_model ? null : 'single-family review — shared-blind-spot risk is NOT mitigated (stamped honestly, never claimed otherwise)',
    live: liveInfo,
    // 2026-08-25 (John-ratified, wording only): the machine's say-so never ships a model —
    // John's ack is the real gate.
    verdict: pass ? `GO — awaiting human ack (grounded · shark-dry · judge lockable · tie-out ${tieOutVerified ? 'verified' : tieOut != null ? 'FAILED but not required — read tie_out.state' : 'not required'})` :
      requireTieOut && !tieOutVerified && grounding.ok ? `BLOCKED (tie-out ${tieOutState})` :
      grounding.ok ? 'BLOCKED (open findings or judge held)' : 'BLOCKED (grounding gate FAILED)',
  };
  record.receipt = buildReceipt(reportText, { nodeValues, declaredInputs, tieOutState, grounding });
  if (outDir) writeRecord(outDir, record, log);
  log(`verdict: ${record.verdict} · cross_model=${cross_model}`);
  log(`RECEIPT (required in the deliverable footer): ${record.receipt.footer_line}`);
  return record;
}

// RECEIPT (2026-08-25, John's rider): binds the exact report bytes + graph values + tie-out
// state to the gate results. A missing footer line marks a deliverable visibly unverified.
function buildReceipt(reportText, { nodeValues, declaredInputs, tieOutState, grounding }) {
  const sha = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
  const report_sha256 = sha(String(reportText));
  const values_sha256 = sha(JSON.stringify({ nodeValues, declaredInputs }));
  const ts = new Date().toISOString();
  return {
    report_sha256, values_sha256, ts,
    footer_line: `financial-analyst receipt ${report_sha256.slice(0, 12)} · grounding ${grounding.ok ? 'CLEAN' : 'FAILED'} (${grounding.checked} checked) · tie-out ${tieOutState} · values ${values_sha256.slice(0, 12)} · ${ts}`,
  };
}

function writeRecord(outDir, record, log) {
  try {
    fs.mkdirSync(outDir, { recursive: true });
    const p = path.join(outDir, 'DEAL-REVIEW.json');
    fs.writeFileSync(p, JSON.stringify(record, null, 2) + '\n', 'utf8');
    log(`wrote ${p}`);
  } catch (e) {
    log(`!! could not write DEAL-REVIEW.json: ${e?.message ?? e}`);
  }
  // Run capture (Skill Foundry "Run capture"); skipped under tests.
  try {
    if (process.env.NODE_TEST_CONTEXT) return;
    const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${record.ts.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({ skill: 'financial-analyst', tier: 'deal-review', started: record.ts,
        result: record.verdict, cross_model: record.cross_model }, null, 2) + '\n', 'utf8');
  } catch { /* best-effort */ }
}

// ── CLI ──────────────────────────────────────────────────────────────────────
function argOf(argv, name) { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : null; }

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    const canon = (p) => {
      const abs = path.resolve(p);
      let real = abs;
      try { real = fs.realpathSync(abs); } catch { /* keep abs */ }
      return process.platform === 'win32' ? real.toLowerCase() : real;
    };
    return canon(fileURLToPath(import.meta.url)) === canon(entry);
  } catch { return false; }
}

if (invokedDirectly()) {
  const argv = process.argv.slice(2);
  const reportPath = argOf(argv, '--report');
  if (!reportPath) {
    console.error('usage: node bin/deal-review.mjs --report <report.md> [--values <nodes.json>] [--inputs <inputs.json>] [--rounds 3] [--live] [--out <dir>]');
    process.exit(2);
  }
  const values = argOf(argv, '--values');
  const inputs = argOf(argv, '--inputs');
  const tieOutPath = argOf(argv, '--tie-out');
  runDealReview({
    reportText: fs.readFileSync(reportPath, 'utf8'),
    nodeValues: values ? JSON.parse(fs.readFileSync(values, 'utf8')) : {},
    declaredInputs: inputs ? JSON.parse(fs.readFileSync(inputs, 'utf8')) : {},
    rounds: Number(argOf(argv, '--rounds')) || 3,
    live: argv.includes('--live'),
    outDir: argOf(argv, '--out'),
    tieOut: tieOutPath ? JSON.parse(fs.readFileSync(tieOutPath, 'utf8')) : null,
    requireTieOut: argv.includes('--require-tie-out'),
  }).then((rec) => {
    // 2026-08-25 exit-code fix (John-ratified; was unverified, now CONFIRMED): the old
    // predicate exited 0 for ANY STOPPED-HONESTLY record — including a FAILED grounding
    // gate — so a script trusting the exit code waved through an ungrounded report.
    process.exit(rec.verdict.startsWith('GO') || rec.verdict.startsWith('UNREVIEWED') ? 0 : 1);
  }).catch((err) => {
    console.error(`deal-review: ${err?.message ?? err}`);
    process.exit(1);
  });
}

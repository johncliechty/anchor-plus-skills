#!/usr/bin/env node
// bin/legal-round.mjs — legal-beagle's ADVERSARIAL REVIEW ENGINE (2026-07-25,
// prose-lock=C amendment in Skill Foundry planning/portfolio-program/
// PORTFOLIO-RIGHTSIZE-2026-07.md).
//
// Before this file, SKILL.md's "Heavy procedure" — fan out one refute reviewer per
// finding, cross-family citation seat, single-family stamping — was PROSE the model
// was asked to follow: no spawner, no tally, no judge, and the honesty stamp was
// self-assigned. The journals prove the pattern pays every time a human ran it by
// hand (0001 wrong-reporter cite caught; 0003 "confirmed 27 changes and caught 3 real
// misses"; 0004 NO-GO overreach refuted down to CONDITIONAL GO). This engine makes it
// ENFORCED instead of remembered.
//
// One canonical copy, consumers import (nothing forked):
//   - Sharks + ≥2-agree BLOCKER tally: crucible/bin/shark-tank.mjs
//   - Context-free judge:              crucible/bin/judge.mjs
//   - Live seats + unforgeable cross_model stamp: researchPrime/bin/live-round-agent.mjs
// The domain layer (new, local): the HARD pre-delivery citation gate — token-level
// lintCitations AND proposition-level lintPropositions (quote-the-authority) — plus
// the legal charter (jurisdiction/date, non-precedential flagging, certainty ceiling).
//
// Usage:
//   node bin/legal-round.mjs --memo <memo.md> --sources <file-or-dir> [--sources ...]
//        [--rounds 3] [--live] [--out <dir>]
//   Without --live / an injected agent: the citation gates still run (deterministic);
//   the adversarial round HONESTLY does not (stamped, never faked).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import process from 'node:process';

import { lintCitations, lintPropositions } from '../src/citation-lint.js';

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

// ── The legal charter (the review round's North Star) ────────────────────────

export function buildLegalCharter() {
  return [
    'LEGAL-REVIEW CHARTER (legal-beagle adversarial engine, 2026-07-25).',
    'The artifact is a legal memo/finding set over a PROVIDED source pack. Refute it:',
    '- [lb1] JURISDICTION + AS-OF DATE: both established up front; every authority',
    '  matched to the governing jurisdiction. (Rule: never cite from memory.)',
    '- [lb2] QUOTE-THEN-ANALYZE: each load-bearing authority is QUOTED from the pack',
    '  before it is characterized; a deterministic gate enforces the quote mechanically',
    '  — flag semantic abuse the gate cannot see (right quote, wrong characterization,',
    '  e.g. the journal-0001 wrong-reporter-cite class).',
    '- [lb3] PRECEDENTIAL WEIGHT: non-precedential authority (PLRs, TAMs, unpublished)',
    '  expressly flagged as such wherever it is load-bearing; never laundered as',
    '  precedent (the journal-0002 PLR class).',
    '- [lb4] CERTAINTY CEILING: no absolute GO/NO-GO where the honest product is',
    '  CONDITIONAL — every load-bearing caveat stays visible (the journal-0004/0006',
    '  overclaiming class: three refuters turned an absolute NO-GO into CONDITIONAL GO).',
    '- [lb5] COMPLETENESS: counter-authority and the strongest opposing reading are',
    '  addressed, not omitted.',
    'A finding MUST set traces_to_north_star and name the criterion id it blocks.',
    'This is analysis-of-sources review, NOT legal advice; the licensed-attorney',
    'boundary in SKILL.md stands.',
  ].join('\n');
}

// ── Source pack loading ──────────────────────────────────────────────────────

export function loadSourcePack(specs) {
  const texts = [];
  const files = [];
  for (const spec of specs) {
    const p = path.resolve(spec);
    if (!fs.existsSync(p)) throw new Error(`source not found: ${spec}`);
    if (fs.statSync(p).isDirectory()) {
      for (const f of fs.readdirSync(p)) {
        const fp = path.join(p, f);
        if (fs.statSync(fp).isFile() && /\.(md|txt)$/i.test(f)) {
          texts.push(fs.readFileSync(fp, 'utf8'));
          files.push(fp);
        }
      }
    } else {
      texts.push(fs.readFileSync(p, 'utf8'));
      files.push(p);
    }
  }
  if (!texts.length) throw new Error('the source pack is empty — the citation gates fail closed without sources');
  return { texts, files };
}

// ── The engine ───────────────────────────────────────────────────────────────

export async function runLegalRound({
  memoText,
  sourceTexts = [],
  rounds = 3,
  agent = null,
  live = false,
  outDir = null,
  log = (m) => process.stderr.write(`${m}\n`),
} = {}) {
  if (typeof memoText !== 'string' || !memoText.trim()) {
    throw new Error('runLegalRound requires the memo text (the artifact under review)');
  }
  if (!Array.isArray(sourceTexts) || !sourceTexts.length) {
    throw new Error('runLegalRound requires a non-empty source pack (fail closed — journal 0006 rule)');
  }

  // 1. HARD PRE-DELIVERY GATES (deterministic, pre-seat, both must pass for GO).
  const tokenLint = lintCitations(memoText, sourceTexts);
  const propLint = lintPropositions(memoText, sourceTexts);
  log(`citation gate: token-level ${tokenLint.ok ? 'CLEAN' : `${tokenLint.violations.length} ungrounded`} · ` +
    `proposition-level ${propLint.ok ? 'CLEAN' : `${propLint.violations.length} unquoted/unsupported`} (${propLint.checked} checked)`);

  // 2. Seats: injected (tests) > live (prefs-aware cross-family) > honest absence.
  let tracker = null;
  let liveInfo = null;
  if (!agent && live) {
    const lra = await import(trioUrl('researchPrime/bin/live-round-agent.mjs'));
    tracker = lra.makeReachedFamilyTracker();
    agent = await lra.buildLiveRoundAgent({ tracker, env: process.env });
    liveInfo = 'live seats bound from coding/review family prefs';
    log(liveInfo);
  }

  const gatesOk = tokenLint.ok && propLint.ok;
  if (!agent) {
    const record = {
      skill: 'legal-beagle', engine: 'legal-round', ts: new Date().toISOString(),
      status: 'GATES-ONLY',
      reason: 'no live model seats (--live) and no injected agent — the adversarial round did NOT run; the deterministic citation gates DID',
      citation_gate: { token: tokenLint, proposition: propLint },
      cross_model: false,
      verdict: gatesOk
        ? 'UNREVIEWED (citation gates PASSED; adversarial round not run)'
        : 'BLOCKED (citation gate FAILED; adversarial round not run)',
    };
    if (outDir) writeRecord(outDir, record, log);
    log(`STOPPED HONESTLY (gates-only): ${record.verdict}`);
    return record;
  }

  const { runSharkTank } = await import(trioUrl('crucible/bin/shark-tank.mjs'));
  const { makeJudge } = await import(trioUrl('crucible/bin/judge.mjs'));
  const northStar = buildLegalCharter();
  // The Sharks read the memo + a bounded slice of the pack (argv budgets — crucible 0004).
  const packBrief = sourceTexts.map((t, i) => `--- SOURCE ${i + 1} (first 4000 chars) ---\n${String(t).slice(0, 4000)}`).join('\n');
  const draft = `${memoText}\n\n=== PROVIDED SOURCE PACK (bounded excerpts; full pack was lint-checked deterministically) ===\n${packBrief}`;

  // 3. Convergence-until-dry over the ≥2-agree tally.
  const roundResults = [];
  const priorBlockerIds = [];
  let lastVerdict = null;
  for (let r = 1; r <= Math.max(1, rounds); r++) {
    const verdict = await runSharkTank({
      agent, northStar, draft, round: r,
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

  // 4. The context-free Judge.
  const judge = makeJudge({ agent, log });
  const judgeVerdict = await judge.decide({
    northStar, findings: lastVerdict?.findings ?? [], round: roundResults.length,
  });

  // 5. Honest stamps — cross_model DERIVED from the tracker, never asserted.
  const families = tracker ? tracker.families() : [];
  const cross_model = families.length > 1;
  const pass = gatesOk && (lastVerdict?.dry === true) && !lastVerdict?.inconclusive && judgeVerdict?.lockable === true;
  const record = {
    skill: 'legal-beagle', engine: 'legal-round', ts: new Date().toISOString(),
    status: 'REVIEWED',
    citation_gate: { token: tokenLint, proposition: propLint },
    rounds: roundResults,
    openBlockers: (lastVerdict?.blockers ?? []).map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, message: b.message })),
    judge: { decision: judgeVerdict?.decision ?? null, lockable: judgeVerdict?.lockable === true, stamp: judgeVerdict?.stamp ?? null },
    cross_model,
    substrate_families: families,
    single_family_note: cross_model ? null : 'single-family review — stamped cross_model:false honestly (journal 0006 rule); shared-blind-spot risk NOT mitigated',
    live: liveInfo,
    verdict: pass ? 'GO (citation-grounded · shark-dry · judge lockable)' :
      gatesOk ? 'BLOCKED (open findings or judge held)' : 'BLOCKED (citation gate FAILED)',
  };
  if (outDir) writeRecord(outDir, record, log);
  log(`verdict: ${record.verdict} · cross_model=${cross_model}`);
  return record;
}

function writeRecord(outDir, record, log) {
  try {
    fs.mkdirSync(outDir, { recursive: true });
    const p = path.join(outDir, 'LEGAL-REVIEW.json');
    fs.writeFileSync(p, JSON.stringify(record, null, 2) + '\n', 'utf8');
    log(`wrote ${p}`);
  } catch (e) {
    log(`!! could not write LEGAL-REVIEW.json: ${e?.message ?? e}`);
  }
  try {
    if (process.env.NODE_TEST_CONTEXT) return;
    const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${record.ts.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({ skill: 'legal-beagle', tier: 'legal-round', started: record.ts,
        result: record.verdict, cross_model: record.cross_model }, null, 2) + '\n', 'utf8');
  } catch { /* best-effort */ }
}

// ── CLI ──────────────────────────────────────────────────────────────────────
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
  const memoPath = (() => { const i = argv.indexOf('--memo'); return i >= 0 ? argv[i + 1] : null; })();
  const sourceSpecs = argv.flatMap((a, i) => (a === '--sources' && argv[i + 1] ? [argv[i + 1]] : []));
  if (!memoPath || !sourceSpecs.length) {
    console.error('usage: node bin/legal-round.mjs --memo <memo.md> --sources <file-or-dir> [--sources ...] [--rounds 3] [--live] [--out <dir>]');
    process.exit(2);
  }
  const roundsIdx = argv.indexOf('--rounds');
  runLegalRound({
    memoText: fs.readFileSync(memoPath, 'utf8'),
    sourceTexts: loadSourcePack(sourceSpecs).texts,
    rounds: roundsIdx >= 0 ? Number(argv[roundsIdx + 1]) || 3 : 3,
    live: argv.includes('--live'),
    outDir: (() => { const i = argv.indexOf('--out'); return i >= 0 ? argv[i + 1] : null; })(),
  }).then((rec) => {
    process.exit(rec.verdict.startsWith('GO') || rec.status === 'GATES-ONLY' && rec.verdict.startsWith('UNREVIEWED') ? 0 : 1);
  }).catch((err) => {
    console.error(`legal-round: ${err?.message ?? err}`);
    process.exit(1);
  });
}

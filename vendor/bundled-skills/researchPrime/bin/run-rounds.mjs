#!/usr/bin/env node
// bin/run-rounds.mjs — THE canonical Phase-3 round driver (T9, 2026-07-11).
//
// Promoted from the root-level run-ramanujan-round.mjs (which every real run had to
// discover by archaeology — journal 0001 hand-rolled a ConPTY harness, the 2026-06-19
// run role-played the engine's rules in sub-agents instead of running the engine).
// This is the documented operator path; the old filename remains as a thin shim.
//
// Faithful ENGINE mode: fresh-context sub-agents produce the cognition (reviewer
// findings, Judge verdict, Synthesizer steer, debate); this driver replays those
// through the REAL trio gates (tallyFindings >=2-agree, gateOneQuorum independence,
// the honest convergence tracker incl. the T8 CLEAN path, the suspiciously-dry
// guard) and assembles the deliverable. No re-implemented gate logic.
//
// Usage:
//   node bin/run-rounds.mjs <runDir> [--max-rounds N]
//     <runDir> holds round-<N>-input.json files:
//       { round, northStar, stakes:{...}|tier,
//         reviews:[{reviewer,angle,lineage,findings:[{claim_id?,topic,severity,traces_to_north_star,message}]}],
//         adjudications:{ judge:{...}, synthesizer:{...}, debate:{...} } }   (replay mode)
//   RESEARCHPRIME_LIVE_ROUND=1  -> reviewer/debate/judge seats go LIVE to Gemini via agy
//     (5:1; agy down => honest HaltError, never Claude self-review).
//   --max-rounds (default 8, env RESEARCHPRIME_MAX_ROUNDS): the HARD round budget — at
//     the cap the run stops with an honest NOT-CONVERGED state file; it never loops
//     unbounded and never fabricates convergence.
//
// Outputs in <runDir>: round-<N>-result.json per round; DELIVERABLE-ENGINE.json on
// convergence (dry OR clean, stamped); RUN-STATE.json always (resume = add the next
// round-input and re-run — every paid result is on disk, nothing is discarded).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  makeConvergenceTracker,
  assessConvergenceHonesty,
  countUnresolvedHighSeverity,
  isDryRound,
  isEmptyRound,
} from './round.mjs';
import { runGovernedRound } from './governor.mjs';
import { deriveGovernorContract } from './formal-governor.mjs';
import { assembleDeliverable, checkOutputConformance } from './deliverable.mjs';
import { calibrationVerdict } from './rho-ledger.mjs';
import { loadGate } from './gate-loader.mjs';
import { HaltError } from './trio-core/contract-core.mjs';
import {
  makeReachedFamilyTracker,
  instrumentRoundAgent,
  buildLiveRoundAgent,
  DEFAULT_ROUND_ROUTES,
  SINGLE_FAMILY_ROUTES,
} from './live-round-agent.mjs';
import { resolveBandRoundBudget } from './intake.mjs';

export async function runRounds(runDir, { maxRounds = null, env = process.env, log = console.log } = {}) {
  const started = new Date().toISOString();
  const t0 = Date.now();

  let governanceRecord;
  try {
    governanceRecord = loadGate(runDir);
  } catch (e) {
    if (e && (e.name === 'HaltError' || e instanceof Error)) {
      const haltRecord = {
        status: 'HALTED',
        reason: e.message,
        timestamp: new Date().toISOString()
      };
      fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify(haltRecord, null, 2));
    }
    throw e;
  }

  const allInputs = fs.readdirSync(runDir)
    .filter((f) => /^round-\d+-input\.json$/.test(f))
    .sort((a, b) => parseInt(a.match(/\d+/)[0]) - parseInt(b.match(/\d+/)[0]))
    .map((f) => JSON.parse(fs.readFileSync(path.join(runDir, f), 'utf8')));
  if (!allInputs.length) throw new Error(`no round-*-input.json found in ${runDir}`);

  // FIELD LAWS, mechanized (2026-08-25, John-ratified card — each of these burned a real
  // round as SKILL.md prose; now the engine HALTs loudly at load, one line, never a silent
  // auto-fix). Law 1: traces_to_north_star is the STRING 'yes'/'no' — a boolean silently
  // demotes EVERY finding (2026-08-15). Law 2: pasted agy replies may arrive ```-fenced
  // ~1-in-6 (0052) — a fenced blob in an input field is a transcription defect, not data.
  // Law 3: any *path* field must be ABSOLUTE (0002 — agy's CWD is never reliable).
  // (Hardening 2026-08-25: violations write HALT-RECORD.json like every other halt; the
  // fence law fires only on a WHOLE-string fence wrap — the pasted-blob signature — so a
  // finding message that merely QUOTES fenced code passes; the path law fires only on
  // filesystem-looking values (has a separator, no scheme) and accepts either OS's
  // absolute form — trio run dirs replay cross-OS.)
  try {
    for (const input of allInputs) {
      const rn = input?.round ?? '?';
      for (const rev of input?.reviews ?? []) {
        for (const f of rev?.findings ?? []) {
          const t = f?.traces_to_north_star;
          if (t !== 'yes' && t !== 'no') {
            throw new Error(`FIELD-LAW HALT round ${rn} reviewer ${rev?.reviewer ?? '?'} topic "${f?.topic ?? '?'}": traces_to_north_star must be the STRING 'yes' or 'no', got ${JSON.stringify(t)} — a non-string silently demotes every finding`);
          }
        }
      }
      const walk = (obj, at) => {
        if (obj == null) return;
        if (typeof obj === 'string') {
          const s = obj.trim();
          if (s.startsWith('```') && s.endsWith('```') && s.length > 6) {
            throw new Error(`FIELD-LAW HALT round ${rn} at ${at}: value is a whole \`\`\`-fenced block — a fenced agy reply was pasted as data; strip the fence and re-run (journal 0052)`);
          }
          return;
        }
        if (Array.isArray(obj)) { obj.forEach((v, i) => walk(v, `${at}[${i}]`)); return; }
        if (typeof obj === 'object') {
          for (const [k, v] of Object.entries(obj)) {
            if (/path$/i.test(k) && typeof v === 'string' && v
                && /[\\/]/.test(v) && !/^[a-z][a-z0-9+.-]*:\/\//i.test(v)
                && !(path.win32.isAbsolute(v) || path.posix.isAbsolute(v))) {
              throw new Error(`FIELD-LAW HALT round ${rn} at ${at}.${k}: "${v}" is not an ABSOLUTE path — agy's CWD is never reliable (journal 0002)`);
            }
            walk(v, `${at}.${k}`);
          }
        }
      };
      walk(input, `round-${rn}-input`);
    }
  } catch (e) {
    try {
      fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify({
        status: 'HALTED', reason: e.message, timestamp: new Date().toISOString(),
      }, null, 2));
    } catch { /* record is best-effort; the halt itself is the law */ }
    throw e;
  }

  // P0 2026-07-25 (journal 0004): a legacy governance record carries the two-gate
  // placeholder `{hash:'mock-hash'}` with NO thresholds/tier — the old `||` short-
  // circuited on that truthy object and crashed at thresholds.N. A locked output is
  // only usable as the contract when it actually CARRIES the contract.
  const locked = governanceRecord.lockedGovernorOutput;
  const lockedUsable = !!(locked && locked.thresholds && locked.tier != null);
  if (locked && !lockedUsable) {
    log('!! governance lockedGovernorOutput carries no governor contract (legacy placeholder record) — deriving the contract from round-1 input');
  }
  const contract = lockedUsable ? locked : deriveGovernorContract(allInputs[0]);
  const thresholds = contract.thresholds;
  const tier = contract.tier;

  // Track B1 W3: sole resolver resolveBandRoundBudget — formal path is fail-closed
  // (missing/unlocked extension → HaltError, never source=default FULL knobs).
  // Cap precedence: explicit CLI maxRounds > env RESEARCHPRIME_MAX_ROUNDS > locked knobs.
  // includeAdjudication from extension knobs only (never argv).
  let band;
  try {
    band = resolveBandRoundBudget({
      runDir,
      maxRounds,
      env,
      failClosed: true,
      fallback: typeof contract.roundBudget === 'number' ? contract.roundBudget : 8,
    });
  } catch (e) {
    if (e && (e.name === 'HaltError' || e instanceof HaltError || e instanceof Error)) {
      const haltRecord = {
        status: 'HALTED',
        reason: e.message,
        code: e.detail?.code ?? e.code ?? 'BAND_BUDGET_HALT',
        timestamp: new Date().toISOString(),
      };
      try {
        fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify(haltRecord, null, 2));
      } catch { /* best-effort HALT-RECORD */ }
    }
    throw e;
  }
  const cap = band.cap;
  const includeAdjudication = band.includeAdjudication;
  log(
    `band: cap=${cap} source=${band.source} includeAdjudication=${includeAdjudication}` +
      (band.knobs?.depth ? ` depth=${band.knobs.depth}` : ''),
  );

  // The HARD budget: never process past the cap; say so loudly (no silent truncation).
  const inputs = allInputs.slice(0, cap);
  const capped = allInputs.length > inputs.length;
  if (capped) log(`!! round budget: processing ${inputs.length}/${allInputs.length} inputs (--max-rounds ${cap})`);

  function replayAgent(adj) {
    return async (_prompt, opts = {}) => {
      const role = opts.role || 'other';
      if (role === 'judge') return adj.judge ?? { decision: 'NOT_CONVERGED', reasons: [] };
      if (role === 'synthesizer') return adj.synthesizer ?? { lean: 'unknown', suggestions: [] };
      if (role === 'debate') return adj.debate ?? { survivor: null };
      return null;
    };
  }

  const tracker = makeConvergenceTracker({ N: thresholds.N });
  const priorBlockerIds = new Set();
  const roundResults = [];
  let roundsToDry = null;

  const reached = makeReachedFamilyTracker();
  const LIVE_ROUND = env.RESEARCHPRIME_LIVE_ROUND === '1';
  const liveAgent = LIVE_ROUND
    ? await buildLiveRoundAgent({ tracker: reached, env }) // prefs-aware (CODING/REVIEW_FAMILY)
    : null;
  if (LIVE_ROUND) {
    log('LIVE cross-family round: seats from coding/review family prefs (omit routes → ~/.anchor/model_prefs.json).');
  }

  for (const inp of inputs) {
    const agent = LIVE_ROUND
      ? liveAgent
      : instrumentRoundAgent({ agent: replayAgent(inp.adjudications ?? {}), routes: SINGLE_FAMILY_ROUTES, tracker: reached });
    // P0 2026-07-25 (T9): route through the GOVERNED round, not bare orchestrateRound.
    // The governor was computed + logged but gated nothing: judge/synthesizer were
    // hard-true at every tier (SKILL.md:94's "tier low fires ZERO" promise was false),
    // and the crit-4 zero-AXIS skip never ran. runGovernedRound is the already-built,
    // already-tested wiring; the band's includeAdjudication knob rides as a
    // tighten-only debate override (LITE can force debate off, never on).
    const result = await runGovernedRound({
      agent,
      stakes: tier,
      round: inp.round,
      northStar: inp.northStar,
      reviews: inp.reviews,
      priorBlockerIds: [...priorBlockerIds],
      includeDebate: includeAdjudication,
    });
    // A SKIPPED round (zero-AXIS) returns the pure tally without the orchestration
    // extras — derive dry/empty from the same predicates the tracker uses.
    const dry = result.dry ?? isDryRound(result);
    const empty = result.empty ?? isEmptyRound(result);
    const obs = tracker.observe(result);
    for (const b of result.tally.blockers) priorBlockerIds.add(b.id);
    if (dry && !empty && roundsToDry == null) roundsToDry = obs.countedRounds;

    const summary = {
      round: result.round,
      verdict: result.tally.verdict,
      dry,
      empty,
      governor: {
        tier: result.tier,
        skipped: result.skipped === true,
        axisFindingCount: result.axisFindingCount,
        reason: result.reason,
        policy: result.policy ? { synthesize: result.policy.synthesize, judge: result.policy.judge, debate: result.policy.debate } : null,
      },
      newBlockers: result.tally.newBlockers.map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, message: b.message })),
      allBlockers: result.tally.blockers.map((b) => b.id),
      demoted: result.tally.demoted.map((d) => ({ id: d.id, message: d.message })),
      quorum: result.quorum ?? null,
      conflicts: result.conflicts ?? [],
      debateFired: result.debate?.fired ?? false,
      judgeVerdict: result.judgeVerdict ?? null,
      direction: result.direction ?? null,
      counts: result.counts,
      trackerState: obs,
    };
    roundResults.push(result);
    fs.writeFileSync(path.join(runDir, `round-${result.round}-result.json`), JSON.stringify(summary, null, 2));
    log(`round ${result.round}: ${result.tally.verdict} | dry=${dry} empty=${empty}${result.skipped ? ' | SKIPPED (zero-AXIS, crit-4)' : ''} | counts=${JSON.stringify(result.counts)} | newBlockers=${result.tally.newBlockers.length} | dryStreak=${obs.dryStreak}/${thresholds.N} emptyStreak=${obs.emptyStreak} | converged=${obs.converged}${obs.mode ? ` (${obs.mode})` : ''}`);
    if (obs.converged) break; // convergence reached — no need to consume further inputs
  }

  const finalState = tracker.state();
  const convergence = {
    converged: finalState.converged,
    mode: finalState.mode,                       // 'dry' | 'clean' | null — never conflated
    stamp: finalState.stamp,                     // the explicit CLEAN stamp when mode==='clean'
    dryStreak: finalState.dryStreak,
    emptyStreak: finalState.emptyStreak,
    countedRounds: finalState.countedRounds,
    rounds: finalState.rounds,
    N: thresholds.N,
    roundBudget: cap,
    roundBudgetHit: capped && !finalState.converged,
  };

  const substrateFamilies = reached.families().length ? reached.families() : ['claude'];
  const finalRound = roundResults[roundResults.length - 1];
  const unresolvedHigh = countUnresolvedHighSeverity(finalRound.tally.findings);
  const honesty = assessConvergenceHonesty({
    stakesTier: tier,
    roundsToDry: roundsToDry ?? finalState.countedRounds,
    unresolvedHighSeverity: unresolvedHigh,
    substrateFamilies,
    thresholds,
  });

  log(`\nTIER=${tier} | convergence=${JSON.stringify(convergence)} | unresolvedHigh=${unresolvedHigh} | substrateFamilies=${JSON.stringify(substrateFamilies)}`);
  log(`HONESTY GUARD: ${JSON.stringify(honesty)}`);

  let deliverable = null;
  if (finalState.converged) {
    // P0 2026-07-25: carry the REAL Wave-9 calibration verdict. Default mode is a pure
    // function of the final round's reviewers (no ledger file needed) — hard-nulling it
    // made every engine deliverable fail its own conformance contract (§ below).
    const calibration = calibrationVerdict({
      reviewers: finalRound?.reviews ?? inputs[inputs.length - 1]?.reviews ?? [],
      useLedger: false,
    });
    deliverable = assembleDeliverable({
      mode: 'engine',
      rounds: roundResults,
      convergence,
      calibration,
      substrateFamilies,
      northStar: inputs[0].northStar,
    });
    // P0 2026-07-25: the engine's OWN output-conformance gate, actually called — the
    // canonical path used to write `verified:true` deliverables that this very check
    // rejects (missing calibration section), and nothing ever ran it. HALT loudly on
    // violation; never ship a deliverable the contract refuses.
    const conformance = checkOutputConformance(deliverable);
    if (!conformance.ok) {
      const haltRecord = {
        status: 'HALTED',
        reason: 'DELIVERABLE output-conformance violation (engine contract)',
        violations: conformance.violations,
        timestamp: new Date().toISOString(),
      };
      fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify(haltRecord, null, 2));
      throw new HaltError(
        `DELIVERABLE conformance violation: ${conformance.violations.join(' | ')}`,
        'the engine deliverable failed its own output contract — fix the assembly, never ship an unconformant deliverable',
      );
    }
    const out = { deliverable, convergence, honesty, tier, thresholds, unresolvedHigh };
    fs.writeFileSync(path.join(runDir, 'DELIVERABLE-ENGINE.json'), JSON.stringify(out, null, 2));
    log(`\nCONVERGED (${convergence.mode}). cross_model=${deliverable.cross_model} verified=${deliverable.verified} rho_mode=${calibration.mode}. Wrote DELIVERABLE-ENGINE.json (output-conformance OK)`);
  } else {
    log(capped
      ? `\nROUND BUDGET HIT (${cap}) without convergence — honest stop; open blockers are in RUN-STATE.json (nothing discarded).`
      : `\nNOT converged yet — need dryStreak ${thresholds.N} (or ${thresholds.N + 1} consecutive clean rounds); add the next round-input after fixing blockers and re-run.`);
  }

  // RUN-STATE.json: the durable state — this file IS the resume mechanism (SKILL.md's
  // honest durability story: round inputs/results on disk, re-run to continue).
  const runState = {
    convergence, honesty, tier, thresholds, unresolvedHigh, substrateFamilies,
    openBlockers: [...priorBlockerIds],
    processedRounds: roundResults.map((r) => r.round),
  };
  fs.writeFileSync(path.join(runDir, 'RUN-STATE.json'), JSON.stringify(runState, null, 2));

  // Run capture for training (Skill Foundry AGENTS.md "Run capture") — best-effort.
  // Skipped under the test runner (P2 2026-07-25): fixture runs must never pollute
  // the training feed (same rule as gandalf/tidy-idy).
  try {
    if (env.NODE_TEST_CONTEXT || process.env.NODE_TEST_CONTEXT) return { convergence, honesty, tier, deliverable, runState };
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = path.join(skillDir, 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({
        skill: 'researchPrime', tier: LIVE_ROUND ? 'live-cross-family' : 'replay',
        started, ended: new Date().toISOString(),
        input: runDir, params: { maxRounds: cap, live: LIVE_ROUND, stakesTier: tier },
        output: finalState.converged ? path.join(runDir, 'DELIVERABLE-ENGINE.json') : path.join(runDir, 'RUN-STATE.json'),
        result: finalState.converged ? `converged (${convergence.mode})` : (capped ? 'round budget hit — honest stop' : 'not converged — awaiting next round'),
        cross_model: deliverable?.cross_model ?? (substrateFamilies.length > 1),
        models: substrateFamilies,
        duration_s: Math.round((Date.now() - t0) / 1000),
        journal_ref: null,
      }, null, 2) + '\n');
  } catch { /* capture is best-effort */ }

  return { convergence, honesty, tier, deliverable, runState };
}

// ---- CLI ----
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}
if (invokedDirectly()) {
  const argv = process.argv.slice(2);
  const runDir = argv.find((a) => !a.startsWith('--'));
  const mrIdx = argv.indexOf('--max-rounds');
  const maxRounds = mrIdx >= 0 ? Number(argv[mrIdx + 1]) : null;
  if (!runDir) { console.error('usage: node bin/run-rounds.mjs <runDir> [--max-rounds N]'); process.exit(2); }
  runRounds(runDir, { maxRounds }).catch((err) => {
    console.error(`run-rounds: ${err?.message ?? err}`);
    process.exit(1);
  });
}

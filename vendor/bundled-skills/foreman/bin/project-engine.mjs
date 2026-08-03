// project-engine.mjs — Foreman Phase 2: MULTI-WAVE auto-advance.
//
// Scope (Phase 2 per Foreman-Implementation-Plan-FINAL.md §11 line 103, AS
// NARROWED by this session's build prompt):
//   Drive the parsed waves of a project IN ASCENDING ORDER, each through the
//   UNCHANGED Phase-1 one-wave engine (runWave): EXECUTE -> orchestrator GATE ->
//   reviewers -> judge -> bounded FIX -> re-gate, with all the §5 guards. Advance
//   to wave N+1 ONLY after wave N reaches a genuine GO through the R2-3-hardened
//   gate (real passing tests). A vacuous-GREEN or ANY §6 HALT on wave N STOPS the
//   whole run — Foreman never advances past an unproven wave. Multi-wave progress
//   is persisted via the atomic §8 checkpoint (current_wave + status + last_verdict
//   encode which waves are done / current). After the final wave GOes, project-DONE
//   is detected per §4.5. The §10 dashboard is emitted each wave (telemetry
//   best-effort). Wave-level resume-from-checkpoint is supported (§8).
//
// Phase 3b ADDS (budget + intra-wave resume, NO git):
//   - budget ENFORCEMENT as a HARD PRE-FLIGHT GATE (§4.6/§6.1): before STARTING a
//     wave, `budget.canStartWave()` (waves + wall-clock) must pass — otherwise the
//     run writes a clean, resumable budget-stop checkpoint and stops BEFORE the
//     unaffordable wave begins. The per-fix-iteration wall-clock gate lives in
//     runWave. The run never overruns by beginning work it cannot finish.
//   - INTRA-WAVE resume: a budget_stopped checkpoint carries intra_wave_step +
//     iteration, so resume re-enters the in-progress wave AT THE GATE (re-proving
//     real passing tests) with its remaining fix budget — resume is never a
//     backdoor to GREEN.
//
// Phase 3c ADDS (git hygiene + git-resume reconciliation, opt-in via `o.git`):
//   - Fresh start: refuse an unexpectedly dirty tree (no clobber), then switch to
//     a dedicated work branch (never the default/main branch). §9.
//   - Per GO wave: runWave commits on the work branch AFTER the hardened gate GOes
//     (commit first, then the checkpoint records last_commit — §8 order); §6.3
//     non-convergence stashes the failed attempt. NEVER pushes/forces/rewrites.
//   - Resume: reconcile the checkpoint's last_commit against actual git HEAD/tree
//     and HALT on divergence (commit-then-crash adopts HEAD; crash-before-commit
//     re-enters at the gate) — git.reconcile() in bin/git-hygiene.mjs.
// All git ops are confined to the target repo. `o.git` absent (the default) keeps
// this file git-free and every Phase-0..3b contract unchanged.
//
// The one-wave contracts (gate, judge, checkpoint, dashboard, all §5 guards) are
// REUSED UNCHANGED from bin/wave-engine.mjs; this file only adds the ascending
// loop, the truth-gated advance, project-DONE detection, resume, and the
// wave-level budget pre-flight.

import fs from 'node:fs';
import path from 'node:path';

import {
  HaltError, locateDocs, parseWaves, discoverTestCommand, preflightTestCommand,
  readCheckpoint, projectDoneDefinition, newCheckpoint, writeCheckpointAtomic, makeBudget,
} from './foreman-lib.mjs';
import { runWave, runGate } from './wave-engine.mjs';
import { makeGitContext } from './git-hygiene.mjs';

/**
 * Resolve the §4 invocation contract for a project, reusing the Phase-0 parsers
 * unchanged. `parseWaves` enforces the finding-I ascending/contiguous guard, so a
 * non-ascending or gapped plan HALTs HERE (HaltError) before any wave runs —
 * Foreman never reorders or fills gaps (§4.3).
 *
 * @returns {{docs, planText, waves, testCmd, totalWaves, gateWarnings?:string[]}}
 */
export function resolveContract(projectDir) {
  const docs = locateDocs(projectDir);
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);      // ascending/contiguous 1..N or HaltError
  const rawCmd = discoverTestCommand(planText, projectDir);
  // cf-slick: refuse known-broken node --test test/ (journals 0038/0047)
  const pre = preflightTestCommand(rawCmd, projectDir);
  const testCmd = { command: pre.command, source: pre.source };
  return {
    docs, planText, waves, testCmd, totalWaves: waves.length,
    gateWarnings: pre.warnings || [],
  };
}

/**
 * Decide which wave to (re)start from when resuming, by reading the §8
 * checkpoint. A torn/schema-breach checkpoint throws HaltError (§8: never
 * best-effort parse a torn file). Returns { startWave, alreadyDone, cp }.
 *
 * Resume reconciliation (wave-level + intra-wave budget resume; git reconciliation
 * is Phase 3c):
 *   - status 'done'                  -> project already complete (alreadyDone).
 *   - status 'halted'                -> HALT: an ERROR halt is NOT auto-resumed;
 *                                       a human must clear the blocker first (§6).
 *   - status 'budget_stopped'        -> CLEAN, resumable budget stop (§6.1). Re-enter
 *                                       the wave we stopped at (current_wave), seeding
 *                                       intra_wave_step + iteration so a mid-fix-loop
 *                                       stop resumes AT THE GATE with its remaining fix
 *                                       budget (re-proves GREEN; never a backdoor).
 *   - status 'running', verdict 'GO' -> current_wave converged; resume at N+1.
 *   - status 'running', verdict != GO-> no wave finished; re-run current_wave fresh
 *                                       (the gate re-establishes truth).
 */
export function planResume(checkpointPath, totalWaves) {
  const cp = readCheckpoint(checkpointPath); // HaltError on torn/invalid -> HALT
  if (cp.status === 'done') return { startWave: totalWaves + 1, alreadyDone: true, cp };
  if (cp.status === 'halted') {
    throw new HaltError(
      'checkpoint is in a HALTED state — cannot auto-resume',
      `wave ${cp.current_wave} stopped with: ${cp.pending_action || '(no recommended action recorded)'}. ` +
        `Clear the blocker, then re-invoke (resume only continues a clean, non-halted checkpoint).`,
    );
  }
  if (cp.status === 'budget_stopped') {
    const startWave = cp.current_wave;
    return {
      startWave,
      alreadyDone: startWave > totalWaves,
      cp,
      resumeWave: startWave,
      // intra_wave_step 'gate' + iteration N -> intra-wave resume (re-enter at gate);
      // 'execute'/iteration 0 -> a wave that never started (run it in full).
      resumeFrom: { iteration: cp.iteration, intraStep: cp.intra_wave_step },
    };
  }
  // status === 'running'
  // F-H sleep fix (0072): a mid-wave crash leaves status=running with
  // intra_wave_step execute|gate|review. Previously we only returned startWave and
  // re-ran EXECUTE from scratch — losing a GREEN gate stamp and re-spending the
  // long execute agent call (observed: B7 W4 died post-gate then re-executed forever).
  const startWave = cp.last_verdict === 'GO' ? cp.current_wave + 1 : cp.current_wave;
  if (cp.last_verdict === 'GO') {
    return { startWave, alreadyDone: startWave > totalWaves, cp };
  }
  return {
    startWave,
    alreadyDone: startWave > totalWaves,
    cp,
    resumeWave: startWave,
    resumeFrom: {
      iteration: Number.isInteger(cp.iteration) ? cp.iteration : 0,
      intraStep: cp.intra_wave_step || 'execute',
    },
  };
}

/**
 * Clear a HALTED checkpoint so `--resume` can continue the run — the HUMAN
 * acknowledgment step §6 requires, made real (previously `go.ps1` passed a
 * `--clear-halt` flag that nothing parsed, so every halt meant hand-editing
 * `foreman-checkpoint.json`).
 *
 * SAFE BY CONSTRUCTION: the halt is cleared to a `budget_stopped` checkpoint
 * seeded at `intra_wave_step:'gate'`, i.e. the ordinary intra-wave resume path.
 * Resume ALWAYS re-runs the orchestrator gate before any GO (see runWave), so
 * clearing a halt can never smuggle in a GREEN — the wave must re-prove real
 * passing tests from the current disk state. The remaining fix budget
 * (`iteration`) is preserved.
 *
 * Non-halted checkpoints are left untouched (idempotent no-op), so the flag is
 * safe to pass unconditionally on every resume, which is exactly what go.ps1
 * has always done.
 *
 * @param {string} checkpointPath
 * @param {{log?:(s:string)=>void}} [o]
 * @returns {{cleared:boolean, status:string, wave?:number, clearedHalt?:?string}}
 */
/**
 * @param {string} checkpointPath
 * @param {{log?:(s:string)=>void, force?:boolean}} [o]
 *   force: allow clear-halt on vacuous-GREEN without code-hypothesis (ops escape hatch)
 */
/**
 * P2 2026-07-25 — `--attest-wave-proven` (F-AT-1: journals 0043/0044/0045, 0074).
 * The SANCTIONED operator path to finish a wave that is verifiably GREEN but whose
 * vacuous-guard cannot see the deliverable (resume/doc-only second pass). Before this,
 * the only exit was hand-editing foreman-checkpoint.json — which the auto-mode
 * classifier correctly refuses as engine-state tampering.
 *
 * NOTHING here weakens the gate: the ORCHESTRATOR re-runs the real gate NOW and it
 * must be genuinely GREEN; the wave's proven ledger must exist and every listed file
 * must be live on disk. The attestation record names the human operator as the party
 * accepting deliverable-exercise on evidence the guard cannot derive — an auditable
 * signed statement, not a bypass flag.
 */
export async function attestWaveProven(checkpointPath, {
  projectDir,
  testCommand,
  log = () => {},
} = {}) {
  const cp = readCheckpoint(checkpointPath);
  if (cp.status !== 'halted') {
    return { attested: false, reason: `checkpoint status is '${cp.status}' — attest applies to a halted wave` };
  }
  const wave = cp.current_wave;
  const foremanDir = path.join(projectDir, '.foreman');
  const ledgerPath = path.join(foremanDir, `wave-${wave}-proven.json`);
  if (!fs.existsSync(ledgerPath)) {
    return { attested: false, reason:
      `no proven ledger at ${ledgerPath} — a wave with no recorded deliverables cannot be attested; ` +
      `land the deliverable (or a source-only wave-${wave}-proven.json) first` };
  }
  let ledger;
  try { ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8')); }
  catch (e) { return { attested: false, reason: `proven ledger unreadable: ${e.message}` }; }
  const files = Array.isArray(ledger.files) ? ledger.files : Array.isArray(ledger) ? ledger : [];
  const missing = files.filter((f) => !fs.existsSync(path.join(projectDir, String(f).replace(/ \(deleted\)$/, ''))));
  if (!files.length || missing.length) {
    return { attested: false, reason: !files.length
      ? 'the proven ledger lists no files — nothing to attest'
      : `ledger file(s) missing on disk: ${missing.slice(0, 5).join(', ')}` };
  }
  // The REAL gate, re-run by the orchestrator, right now. TIMEOUT/vacuous/RED all refuse.
  log(`attest: re-running the gate for wave ${wave} (orchestrator-owned; must be genuinely GREEN)…`);
  const gate = await runGate({ projectDir, testCommand, foremanDir, wave: { n: wave }, iteration: 0 });
  if (!gate.green) {
    return { attested: false, reason:
      `the gate is not GREEN (${gate.gate_class ?? 'RED'}${gate.vacuous_reason ? `: ${gate.vacuous_reason}` : ''}) — attest never overrides the gate` };
  }
  const record = {
    attested_by: 'human-operator (--attest-wave-proven)',
    ts: new Date().toISOString(),
    wave,
    gate_artifact: gate.artifact_path,
    gate: { exit_code: gate.exit_code, tests: gate.tap.tests, pass: gate.tap.pass, fail: gate.tap.fail },
    ledger: ledgerPath,
    ledger_files: files,
    statement:
      'The operator attests these ledger deliverables are this wave\'s work and are exercised — ' +
      'accepted on human evidence the vacuous-guard cannot derive (F-AT-1). The gate above ran GREEN at attest time.',
  };
  const attestPath = path.join(foremanDir, `wave-${wave}-attested.json`);
  fs.writeFileSync(attestPath, JSON.stringify(record, null, 2) + '\n', 'utf8');
  const terminal = wave >= (cp.total_waves ?? wave);
  cp.last_verdict = 'GO';
  cp.status = terminal ? 'done' : 'budget_stopped';
  if (!terminal) cp.current_wave = wave + 1;
  cp.intra_wave_step = 'execute'; // next entry point (fresh wave / done-state inert)
  cp.iteration = 0;
  cp.pending_action = terminal
    ? `project DONE via human attestation of terminal wave ${wave} (see ${attestPath}; gate GREEN at attest time)`
    : `wave ${wave} completed via human attestation (${attestPath}); --resume proceeds to wave ${wave + 1}`;
  writeCheckpointAtomic(checkpointPath, cp);
  log(`attest: wave ${wave} GO by attestation → ${attestPath}; checkpoint ${cp.status}` +
    (terminal ? '' : ` @ wave ${cp.current_wave}`));
  return { attested: true, wave, attestPath, terminal, gate: record.gate };
}

export function clearHaltedCheckpoint(checkpointPath, { log = () => {}, force = false } = {}) {
  const cp = readCheckpoint(checkpointPath); // HaltError on torn/invalid — never guess
  if (cp.status !== 'halted') {
    log(`clear-halt: checkpoint status is '${cp.status}' — nothing to clear`);
    return { cleared: false, status: cp.status };
  }
  const clearedHalt = cp.pending_action ?? null;
  // Sleep 0076 package 3 / 0079: vacuous-GREEN clear-halt without new source is thrash.
  const isVacuous = typeof clearedHalt === 'string' && /vacuous-GREEN/i.test(clearedHalt);
  if (isVacuous && !force) {
    const msg =
      `clear-halt REFUSED for vacuous-GREEN (journals 0076/0078/0079): re-clearing alone ` +
      `re-enters empty execute. Land import-tested source for wave ${cp.current_wave} ` +
      `(or a source-only wave-${cp.current_wave}-proven.json), then --resume — or pass force:true / --force.`;
    log(`clear-halt: ${msg}`);
    // Stay halted; stamp guidance without clearing status
    cp.pending_action = msg + (clearedHalt ? ` — was: ${clearedHalt}` : '');
    writeCheckpointAtomic(checkpointPath, cp);
    return {
      cleared: false,
      status: 'halted',
      wave: cp.current_wave,
      clearedHalt,
      refused: true,
      reason: 'vacuous-GREEN',
      reentry: null,
    };
  }
  cp.status = 'budget_stopped';
  // Phase A (2026-07-22): PLAN-AMENDMENT clear-halt re-enters at EXECUTE (iteration 0)
  // so the wave does not gate-only on already-applied code and false-vacuous-GREEN
  // (journals 0040, 0045). Other halts still re-enter at the gate and re-prove GREEN.
  // Vacuous with force re-enters EXECUTE so a newly landed delta is applied.
  const isPlanAmendment = typeof clearedHalt === 'string' &&
    /PLAN-AMENDMENT/i.test(clearedHalt);
  const reenterExecute = isPlanAmendment || (isVacuous && force);
  if (reenterExecute) {
    cp.intra_wave_step = 'execute';
    cp.iteration = 0;
    cp.pending_action =
      isPlanAmendment
        ? (`halt cleared by human (--clear-halt) after PLAN-AMENDMENT — re-enter EXECUTE ` +
          `(iteration reset); gate still re-proves GREEN before GO` +
          (clearedHalt ? ` — was: ${clearedHalt}` : ''))
        : (`halt cleared by human (--clear-halt --force) after vacuous-GREEN — re-enter EXECUTE ` +
          `(iteration reset); you MUST have landed import-tested source first` +
          (clearedHalt ? ` — was: ${clearedHalt}` : ''));
    log(`clear-halt: wave ${cp.current_wave} ${isPlanAmendment ? 'PLAN-AMENDMENT' : 'vacuous(force)'} ` +
      `halt cleared -> budget_stopped @ execute (iteration 0); resume will re-run EXECUTE then re-prove GREEN`);
  } else {
    cp.intra_wave_step = 'gate';
    cp.pending_action = `halt cleared by human (--clear-halt)${clearedHalt ? ` — was: ${clearedHalt}` : ''}`;
    log(`clear-halt: wave ${cp.current_wave} halt cleared -> budget_stopped @ gate (iteration ${cp.iteration} preserved); ` +
      `resume will re-prove GREEN through the orchestrator gate`);
  }
  writeCheckpointAtomic(checkpointPath, cp);
  return {
    cleared: true,
    status: cp.status,
    wave: cp.current_wave,
    clearedHalt,
    reentry: reenterExecute ? 'execute' : 'gate',
  };
}

/**
 * Run a whole project: every parsed wave, in ascending order, to a genuine GO,
 * then project-DONE. Stops the entire run on the first non-GO wave.
 *
 * @param {object} o
 * @param {string}  o.projectDir
 * @param {object}  [o.driver]                 single driver used for every wave
 * @param {(wave)=>object} [o.driverFor]       per-wave driver factory (takes precedence)
 * @param {number}  [o.reviewerCount=2]
 * @param {number}  [o.fixIterCap=4]           §6.3 per-wave MAX_ITERS (unchanged)
 * @param {boolean} [o.resume=false]           continue from the on-disk checkpoint
 * @param {object}  [o.budget]                 a pre-built §4.6 budget (makeBudget); takes precedence
 * @param {object}  [o.budgetConfig]           { maxWaves?, maxWallClockMs?, now? } -> makeBudget
 * @param {string}  [o.foremanDir]             default <projectDir>/.foreman
 * @param {string}  [o.checkpointPath]         default <projectDir>/foreman-checkpoint.json
 * @param {boolean|object} [o.git]             Phase 3c git hygiene (opt-in; falsy = off).
 *                                             Truthy enables commit-on-GO + reconcile;
 *                                             `{ branch }` overrides the work branch.
 * @param {object}  [o.gitContext]             a pre-built makeGitContext (tests inject this)
 * @param {(s:string)=>void} [o.log]
 * @returns {Promise<object>} { status:'DONE'|'HALT'|'BUDGET-STOP', stoppedAt?, haltReason?, waveResults[], ... }
 */
export async function runProject(o) {
  const { projectDir, driver, driverFor, reviewerCount = 2, fixIterCap = 4, resume = false } = o;
  const foremanDir = o.foremanDir || path.join(projectDir, '.foreman');
  const checkpointPath = o.checkpointPath || path.join(projectDir, 'foreman-checkpoint.json');
  const log = o.log || (() => {});

  // ---- Phase 3c git hygiene (OPTIONAL — null = no git, every prior contract intact) ----
  // makeGitContext HALTs if git is requested but the project is not a repo, and the
  // containment guard hard-refuses any repo that contains the Foreman source.
  const gitCtx = o.gitContext ||
    (o.git ? makeGitContext({ repoDir: projectDir, workBranch: (o.git && o.git.branch) || undefined, log }) : null);

  // ---- §4.6 budget (HARD pre-flight gate; OPTIONAL — null = no budget stop) ----
  // A pre-built budget wins (tests inject a clock); else build one from budgetConfig.
  // makeBudget HALTs (HaltError) on an invalid cap or an unreadable clock — the
  // conservative §10 fallback (refuse to run unbounded) fires HERE, before any wave.
  const budget = o.budget ||
    (o.budgetConfig ? makeBudget({ maxFixItersPerWave: fixIterCap, ...o.budgetConfig }) : null);
  if (budget) {
    log(`budget: ${budget.maxWaves == null ? 'unlimited' : budget.maxWaves} wave(s) this run · ` +
      `${budget.maxWallClockMs == null ? 'no' : Math.round(budget.maxWallClockMs / 1000) + 's'} wall-clock cap · ` +
      `fix-iter cap ${budget.maxFixItersPerWave} (enforced as a HARD pre-flight gate)`);
  }

  // ---- §4 contract (ascending/contiguous guard HALTs a bad plan here) ----
  const { docs, waves, testCmd, totalWaves, gateWarnings = [] } = resolveContract(projectDir);
  log(`contract: ${totalWaves} wave(s) · gate "${testCmd.command}" (${testCmd.source})`);
  for (const w of gateWarnings) log(`gate preflight WARNING: ${w}`);

  // ---- decide the starting wave (wave-level + intra-wave resume) ----
  let startWave = 1;
  let resumeWave = null;     // the single wave to seed with resumeFrom (budget resume)
  let resumeFrom = null;     // { iteration, intraStep } -> intra-wave seed for runWave
  if (resume) {
    // ---- §8 git-resume RECONCILIATION (BEFORE planResume) ----
    // Compare the checkpoint's last_commit to actual git HEAD/tree and HALT on
    // divergence rather than blind-proceeding. A commit-then-crash (HEAD exactly 1
    // commit ahead of last_commit) is recovered by ADOPTING HEAD and marking that
    // wave GO in the checkpoint, so the normal resume logic advances WITHOUT
    // redoing or re-committing it (§8: "adopt HEAD … rather than redo the wave").
    // A crash-before-commit (HEAD == last_commit, in-progress dirty tree) re-enters
    // the wave at the gate. Run on EVERY resume so a rewritten history is caught
    // even under a 'done' checkpoint.
    if (gitCtx) {
      const cp0 = readCheckpoint(checkpointPath); // HaltError on torn -> HALT
      const rec = gitCtx.reconcile(cp0);          // HaltError on divergence/wrong-branch/unexpected-dirty
      log(`git reconcile: ${rec.detail}`);
      if (rec.action === 'adopt-head') {
        cp0.last_commit = rec.adoptedHead;
        cp0.last_verdict = 'GO';
        cp0.intra_wave_step = 'done';
        cp0.status = cp0.current_wave >= totalWaves ? 'done' : 'running';
        cp0.pending_action =
          `git reconcile adopted HEAD ${String(rec.adoptedHead).slice(0, 7)} for wave ${cp0.current_wave} ` +
          `(commit-then-crash) — advancing without re-commit (§8)`;
        writeCheckpointAtomic(checkpointPath, cp0);
      }
    }
    const r = planResume(checkpointPath, totalWaves); // reads the (reconciled) checkpoint
    if (r.alreadyDone) {
      const done = projectDoneDefinition(waves);
      log(`resume: checkpoint reports project already DONE (status=${r.cp.status}, wave ${r.cp.current_wave}/${totalWaves})`);
      return { status: 'DONE', projectDone: done, resumed: true, startWave: totalWaves + 1,
        waveResults: [], checkpointPath, totalWaves };
    }
    startWave = r.startWave;
    resumeWave = r.resumeWave ?? null;
    resumeFrom = r.resumeFrom ?? null;
    log(`resume: continuing from wave ${startWave}/${totalWaves} ` +
      `(checkpoint: wave ${r.cp.current_wave}, verdict ${r.cp.last_verdict}, status ${r.cp.status})` +
      (resumeWave ? ` · intra-wave seed: step=${resumeFrom.intraStep}, iter=${resumeFrom.iteration}` : ''));
  } else if (gitCtx) {
    // ---- §9 fresh-start preflight: dirty-tree HALT (no clobber) + dedicated branch ----
    const prep = gitCtx.prepareFreshStart(); // HaltError on dirty tree / unborn HEAD
    log(`git: on dedicated work branch "${gitCtx.workBranch}"` +
      (prep.created ? ` (created from "${prep.baseBranch}")` : ` (base branch "${prep.baseBranch}" untouched)`) +
      (gitCtx.hasRemote() ? '' : ' · no remote configured (push is out of scope anyway)'));
  }

  // Write a CLEAN, resumable wave-level budget-stop checkpoint for wave `k` that was
  // never started (distinct from runWave's intra-wave budget stop). Reuses §8 fields
  // only: status 'budget_stopped' + last_verdict 'BUDGET-STOP' + intra_wave_step
  // 'execute' (never started) + iteration 0 + the budget_remaining snapshot.
  function writeWaveLevelBudgetStop(k, dimension, reason) {
    const cp = newCheckpoint({ plan_path: docs.plan, total_waves: totalWaves, reviewer_count: reviewerCount });
    cp.current_wave = k;
    cp.intra_wave_step = 'execute';
    cp.iteration = 0;
    cp.last_verdict = 'BUDGET-STOP';
    cp.status = 'budget_stopped';
    cp.budget_remaining = budget.snapshotForCheckpoint();
    cp.pending_action =
      `BUDGET STOP (${dimension}) before starting wave ${k}/${totalWaves}: ${reason}. ` +
      `Wave ${k} was NOT started. This is a clean, resumable checkpoint — re-invoke with --resume once the ` +
      `budget / Pro usage window resets (§7), or raise the cap. Resume starts wave ${k} from EXECUTE and must ` +
      `reach a real GREEN gate before any GO.`;
    writeCheckpointAtomic(checkpointPath, cp);
    return cp;
  }

  // Write a CLEAN, resumable IN-PROGRESS checkpoint for wave `k` BEFORE it executes
  // (P1 crash-resilience). Carries last_commit forward from the prior wave (or the
  // current git HEAD) so reconcile can distinguish crash-before-commit (HEAD ==
  // last_commit, dirty) from commit-then-crash (HEAD 1 ahead). status 'running' +
  // last_verdict null ⇒ resumableInProgress in reconcile/planResume.
  function writeWaveStartCheckpoint(k) {
    let cp;
    try { cp = readCheckpoint(checkpointPath); }
    catch { cp = newCheckpoint({ plan_path: docs.plan, total_waves: totalWaves, reviewer_count: reviewerCount }); }
    cp.plan_path = docs.plan;
    cp.current_wave = k;
    cp.total_waves = totalWaves;
    cp.intra_wave_step = 'execute';
    cp.iteration = 0;
    cp.last_verdict = null;
    cp.status = 'running';
    // NOTE: do NOT call budget.snapshotForCheckpoint() here — it reads the clock,
    // and the authoritative budget snapshot is written by runWave on stop/GO. The
    // carried-forward budget_remaining (from the prior checkpoint or newCheckpoint
    // default) is a fine placeholder for this transient in-progress marker.
    if (gitCtx) { const h = gitCtx.headSha(); if (h) cp.last_commit = h; }
    cp.pending_action =
      `wave ${k}/${totalWaves} in progress (execute) — if interrupted, re-invoke with --resume; ` +
      `intra-wave seed re-enters at gate/review when stamped (always re-proves GREEN before GO)`;
    writeCheckpointAtomic(checkpointPath, cp);
    return cp;
  }

  // ---- ascending wave loop ----
  const waveResults = [];
  for (let k = startWave; k <= totalWaves; k++) {
    const wave = waves[k - 1];
    // Belt-and-suspenders: parseWaves already guarantees waves[k-1].n === k for a
    // contiguous ascending 1..N plan; assert it so a future parser change cannot
    // silently run waves out of order (§4.3 "never reorder").
    if (wave.n !== k) {
      throw new HaltError(
        'wave iteration is not ascending/contiguous',
        `expected wave ${k} at position ${k}, found wave ${wave.n} — refusing to run out of order`,
      );
    }

    // ---- §6.1 BUDGET PRE-FLIGHT (HARD GATE): can we AFFORD to START wave k? ----
    // If not, do NOT start it: write a clean resumable budget-stop checkpoint and
    // stop. The unaffordable wave never begins (never partially runs).
    if (budget) {
      const pf = budget.canStartWave();
      if (!pf.ok) {
        const cp = writeWaveLevelBudgetStop(k, pf.dimension, pf.reason);
        log(`⏸ BUDGET STOP before wave ${k}/${totalWaves} (${pf.dimension}): ${pf.reason}; ` +
          `wave ${k} NOT started; waves ${k}..${totalWaves} remain (resumable)`);
        return {
          status: 'BUDGET-STOP', stoppedAt: k, dimension: pf.dimension,
          haltReason: `budget stop (${pf.dimension}): ${pf.reason}`,
          recommend: cp.pending_action, waveResults, checkpointPath, totalWaves,
          finalCheckpoint: cp,
        };
      }
      // P3B-7 fix: count this wave as STARTED now — i.e. after the budget
      // PRE-FLIGHT (canStartWave) passed and BEFORE runWave / the test gate runs.
      // "max waves to START this run" is counted at commit-to-start, which is the
      // correct semantics; the old comment ("only after the gate passed") wrongly
      // implied the test gate. No behavior change.
      budget.startWave();
    }

    const drv = driverFor ? driverFor(wave) : driver;
    if (!drv) throw new TypeError('runProject requires `driver` or `driverFor`');

    // ---- crash-resilience (P1): mark wave k IN-PROGRESS on disk BEFORE execute ----
    // Without this, no checkpoint exists until a wave FINISHES, so a crash mid-wave
    // (the OS-freeze case) leaves nothing for --resume to read and forces a manual
    // salvage. status 'running' + last_verdict null makes reconcile treat the dirty
    // tree as an in-progress wave (resumableInProgress) and re-enter at the gate;
    // last_commit = current HEAD anchors the commit-then-crash check. runWave
    // overwrites this with the real end-of-wave checkpoint, so it is a no-op for a
    // normal (non-crashing) run.
    writeWaveStartCheckpoint(k);

    log(`── wave ${k}/${totalWaves} "${wave.title || '(untitled)'}" ───────────────`);
    const result = await runWave({
      projectDir, testCommand: testCmd.command, wave, totalWaves,
      planPath: docs.plan, driver: drv, reviewerCount, fixIterCap, budget,
      resumeFrom: (k === resumeWave ? resumeFrom : null),
      git: gitCtx, // Phase 3c: commit-on-GO + §6.3 stash live in runWave (null = no git)
      foremanDir, checkpointPath, log,
    });

    waveResults.push({
      wave: k,
      title: wave.title || '',
      status: result.status,
      iterations: result.iterations,
      tap: result.gate ? result.gate.tap : null,
      green: result.gate ? result.gate.green : null,
      haltReason: result.haltReason || null,
      dashboard: result.dashboard,
    });

    // ---- intra-wave BUDGET STOP (runWave already wrote the resumable checkpoint) ----
    if (result.status === 'BUDGET-STOP') {
      log(`⏸ run BUDGET-STOPPED mid-wave ${k}/${totalWaves} (${result.dimension}): ${result.haltReason}; ` +
        `waves ${k + 1}..${totalWaves} NOT run; wave ${k} resumes at the gate (resumable)`);
      return {
        status: 'BUDGET-STOP', stoppedAt: k, dimension: result.dimension,
        haltReason: result.haltReason, recommend: result.recommend,
        waveResults, checkpointPath, totalWaves, finalCheckpoint: result.checkpoint,
      };
    }

    // ---- truth-gated advance: ONLY a genuine GO advances (§5) ----
    if (result.status !== 'GO') {
      // STOP the whole run. runWave already wrote the §8 checkpoint with status
      // 'halted' + the exact recommended next action. We never touch wave k+1.
      log(`✗ run STOPPED at wave ${k}/${totalWaves}: ${result.status}` +
        (result.haltReason ? ` — ${result.haltReason}` : '') +
        `; waves ${k + 1}..${totalWaves} NOT run (unproven wave never auto-advances)`);
      return {
        status: 'HALT', stoppedAt: k, haltReason: result.haltReason,
        recommend: result.recommend, waveResults, checkpointPath, totalWaves,
        finalCheckpoint: result.checkpoint,
      };
    }

    // GO: the per-wave checkpoint now encodes progress (current_wave=k,
    // last_verdict=GO; status='running' until the terminal wave sets 'done').
    log(`✓ WAVE ${k} COMPLETED SUCCESSFULLY!`);
    if (k < totalWaves) {
      log(`→ advancing to wave ${k + 1}/${totalWaves}`);
    }
  }

  // ---- all waves GREEN -> project-DONE (§4.5) ----
  // The terminal wave's runWave already wrote the checkpoint with status 'done'.
  const done = projectDoneDefinition(waves);
  log(`✓ PROJECT DONE — all ${totalWaves} wave(s) GREEN via the orchestrator-run gate; ` +
    `${done.predicate}`);
  return {
    status: 'DONE', projectDone: done, waveResults, checkpointPath, totalWaves,
    startWave,
  };
}

export const _internals = { resolveContract, planResume };

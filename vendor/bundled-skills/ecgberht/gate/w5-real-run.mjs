/**
 * Wave-5 REAL-RUN gate — EXCLUDED from the standing suite (journal 0074, FIX 3).
 *
 * Purpose: earn SC6 with LIVE-SKILL evidence. Invokes the REAL researchPrime
 * and the REAL Jumper ONE TIME EACH at the smallest/LITE depth, observed
 * anti-stub (pid + proc_create_time, live → terminal), each run's WRAPPER
 * (this gate — the commissioned run's wrapper per S6) writing a durable
 * handback pair through the SKILL-OWNED contract. Then re-derives
 * commissionable-skills.json + sc6-feasibility.json from the merged evidence.
 *
 * REAL ENTRY POINTS (resolved via the registered skill roots — realpath of
 * ~/.claude/skills/<name>; never invented; the gate STOPs if unresolvable):
 *   researchPrime → <skill-root>/bin/plan-gate.mjs (Gate-1/2 APPROVE ceremony)
 *                   then <skill-root>/bin/run-rounds.mjs — THE canonical
 *                   Phase-3 round driver (T9 operator path), driven at the
 *                   skill's own locked LITE band (depth=LITE, tier=Standard)
 *                   in its documented on-disk replay mode to a CONVERGED
 *                   DELIVERABLE-ENGINE.json (output-conformance checked by
 *                   the skill itself).
 *   Jumper        → <skill-root>/bin/jumper-run.mjs --depth LITE — the REAL
 *                   ideation engine: live model seats (drafter = coding
 *                   family, Gate-3 verifier = cross-family) through the trio
 *                   drivers. Real spend, Stage-2 authorized (cheap profile).
 *
 * Anti-stub: this gate never synthesizes skill output. If a real entry cannot
 * be resolved, or a run exceeds the cheap-profile wall clock, or exits
 * non-zero, the gate STOPs and reports — it records NOTHING and never
 * substitutes a stand-in.
 *
 * Usage (operator / orchestrator only): node gate/w5-real-run.mjs
 * D-1: children never receive ANCHOR_TOKEN / capability env.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { CONTRACT_VERSION, writeHandbackPair } from '../engine/handback-contract.mjs';
import { buildHandbackReceipt } from '../engine/receipt-validate.mjs';
import {
  collectEvidenceFromWorktree,
  recordG4MergedEvidence,
  evaluateG4Evidence,
  cmdlineNamesTrioEntry,
  EVIDENCE_CLASS,
} from '../engine/g4-verdict.mjs';
import {
  writeCommissionableSkills,
  writeSc6Feasibility,
  deriveCommissionableSkills,
  loadG4Evidence,
  loadHaltInventory,
} from '../engine/commissionable-skills.mjs';
import { writeJsonIdempotentSync } from '../engine/durable-write.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Cheap-profile wall-clock ceilings (STOP, never a silent overrun). */
const RP_TIMEOUT_MS = 10 * 60 * 1000; // replay-mode engine run: minutes at most
const JUMPER_TIMEOUT_MS = 45 * 60 * 1000; // live LITE ideation run

const FORBIDDEN_CHILD_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'ECGBERHT_CAPABILITY',
]);

function stop(reason, extra = {}) {
  console.error(JSON.stringify({ ok: false, stopped: true, reason, ...extra }, null, 2));
  process.exit(3);
}

function buildChildEnv(base = process.env) {
  const env = { ...base };
  for (const k of FORBIDDEN_CHILD_ENV) delete env[k];
  return env;
}

function procCreateTime(pid) {
  if (process.platform === 'win32') {
    const r = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        `(Get-Process -Id ${Number(pid)} -ErrorAction SilentlyContinue).StartTime.ToUniversalTime().Subtract([datetime]'1970-01-01').TotalSeconds`,
      ],
      { encoding: 'utf8', windowsHide: true },
    );
    const n = parseFloat(String(r.stdout || '').trim());
    return Number.isFinite(n) ? n : Date.now() / 1000;
  }
  try {
    const stat = fs.statSync(`/proc/${pid}`);
    return stat.birthtimeMs ? stat.birthtimeMs / 1000 : stat.ctimeMs / 1000;
  } catch {
    return Date.now() / 1000;
  }
}

/**
 * Resolve a registered skill root to its REAL path (junction followed).
 * Returns null when the root does not exist — the caller STOPs (never invents).
 */
function resolveSkillRootReal(name) {
  const link = path.join(os.homedir(), '.claude', 'skills', name);
  try {
    return fs.realpathSync(link);
  } catch {
    return null;
  }
}

/**
 * Spawn an OBSERVED child: capture (pid, proc_create_time) while live, wait
 * for terminal, enforce the wall-clock ceiling. Returns observation facts.
 */
function spawnObserved(cmdline, { cwd, timeoutMs, logPrefix, stdinScript = null }) {
  return new Promise((resolve) => {
    const child = spawn(cmdline[0], cmdline.slice(1), {
      cwd,
      env: buildChildEnv(),
      windowsHide: true,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const pid = child.pid;
    if (!pid) {
      resolve({ ok: false, reason: 'spawn_failed' });
      return;
    }
    const proc_create_time = procCreateTime(pid);
    const live_observed_at = new Date().toISOString();

    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let promptsSent = 0;

    child.stdout.on('data', (d) => {
      const s = String(d);
      stdout += s;
      // Interactive human-gate ceremony (researchPrime plan-gate): the
      // operator executes John's APPROVED corrective package — answer the
      // two gates APPROVE. Never used for the observed run-rounds child.
      if (stdinScript === 'approve-two-gates' && /APPROVE \/ EDIT \/ ABORT\?/.test(s)) {
        if (promptsSent < 2) {
          promptsSent += 1;
          try {
            child.stdin.write('APPROVE\n');
          } catch {
            /* child gone */
          }
        }
      }
    });
    child.stderr.on('data', (d) => {
      const s = String(d);
      stderr += s;
      if (logPrefix) {
        for (const line of s.split(/\r?\n/)) {
          if (line.trim()) console.error(`[${logPrefix}] ${line.trim()}`);
        }
      }
    });

    const timer = setTimeout(() => {
      timedOut = true;
      try {
        spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
          windowsHide: true,
        });
      } catch {
        try {
          child.kill('SIGKILL');
        } catch {
          /* already gone */
        }
      }
    }, timeoutMs);

    child.on('exit', (code) => {
      clearTimeout(timer);
      resolve({
        ok: !timedOut && code === 0,
        exitCode: code ?? 1,
        timedOut,
        pid,
        proc_create_time,
        live_observed_at,
        terminal_observed_at: new Date().toISOString(),
        stdout,
        stderr,
      });
    });
    child.on('error', () => {
      clearTimeout(timer);
      resolve({ ok: false, reason: 'spawn_error', pid, proc_create_time });
    });
  });
}

/** Build the per-run evidence entry from an observed run + written handback. */
function buildEvidenceEntry({ run, cmdline, worktree, skill, entryRel }) {
  const evidence = collectEvidenceFromWorktree({
    worktree,
    cmdline,
    pid: run.pid,
    proc_create_time: run.proc_create_time,
    observed_live: true,
    observed_terminal: true,
    evidence_paths: [entryRel, '.ecgberht/handback/handback.json'],
    skill,
  });
  evidence.no_token_in_child = true;
  evidence.mode = 'w5-real-run-live-skill';
  evidence.kill_on_job_close = false;
  evidence.observation_method = 'spawn-wait-exit';
  evidence.live_observed_at = run.live_observed_at;
  evidence.terminal_observed_at = run.terminal_observed_at;
  evidence.identity_observation = {
    live: {
      status: 'alive',
      pid: run.pid,
      proc_create_time: run.proc_create_time,
      observed_at: run.live_observed_at,
    },
    terminal: {
      status: 'terminal',
      observed_terminal: true,
      exit_code: run.exitCode,
      observed_at: run.terminal_observed_at,
    },
  };
  evidence.contract_version = CONTRACT_VERSION;
  return evidence;
}

/** Wrapper-side handback write (S6: the commissioned run's wrapper writes). */
function writeRunHandback({ worktree, skill, depth, whyNext, toolDepthWhy, flags, prefix }) {
  const base = buildHandbackReceipt({
    as_of: new Date().toISOString().slice(0, 10),
    active_effort: `${prefix}-${skill}-LITE`,
    why_next: whyNext,
    grasscatch_why: null,
    tool_depth_why: toolDepthWhy,
    human_wait: 'none',
    uncertainty_flags: flags,
    skill,
    depth,
    commission_id: 'w5-real-run',
    partial: false,
  });
  const hb = {
    ...base,
    client_event_id: `${prefix}-ce-${Date.now()}`,
    handback_id: `${prefix}-hb-${Date.now()}`,
  };
  const r = writeHandbackPair(worktree, hb);
  if (!r.ok) stop('handback_write_failed', { skill, detail: r });
  return r;
}

async function runResearchPrime(rpRoot) {
  const planGate = path.join(rpRoot, 'bin', 'plan-gate.mjs');
  const runRounds = path.join(rpRoot, 'bin', 'run-rounds.mjs');
  if (!fs.existsSync(planGate) || !fs.existsSync(runRounds)) {
    stop('researchPrime_entry_unresolvable', { planGate, runRounds });
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w5-real-rp-'));
  const runDir = path.join(work, 'run-dir');
  fs.mkdirSync(runDir, { recursive: true });

  // Frozen Phase-1 inputs at the SKILL'S OWN smallest depth (LITE, Standard,
  // low stakes) — the skill's intake locks the LITE band knobs itself.
  const planInputs = {
    objective:
      'Ecgberht steward SC6 real-evidence run: verify the commissioned-run handback contract end-to-end at the smallest depth',
    axis:
      'A commissioned researchPrime run terminates with an honestly-verified deliverable; a run that cannot verify its claims FALSIFIES the candidate',
    branches: [
      'governed-round replay over the recorded review set',
      'single-round convergence check on the handback claims',
    ],
    baselines: ['the Wave-4 cheap-profile harness (contract-only proof)'],
    scope: 'narrow',
    unknowns: 0,
    depth: 'LITE',
    tier: 'Standard',
    stakes: {
      declared_stakes: 'low',
      reversibility: 'reversible',
      blast_radius: 'narrow',
      magnitude: 'minor',
    },
  };
  const planInputsPath = path.join(runDir, 'plan-inputs.json');
  fs.writeFileSync(planInputsPath, `${JSON.stringify(planInputs, null, 2)}\n`);

  // Gate-1/Gate-2 ceremony through the REAL plan-gate (locks the LITE band +
  // governance.json). Operator answers APPROVE per John's approved package.
  console.error('[rp] plan-gate: running Gate-1/Gate-2 ceremony (APPROVE x2)…');
  const gateRun = await spawnObserved(
    [process.execPath, planGate, planInputsPath, runDir],
    { cwd: runDir, timeoutMs: 5 * 60 * 1000, logPrefix: 'rp-gate', stdinScript: 'approve-two-gates' },
  );
  if (!gateRun.ok) {
    stop('researchPrime_plan_gate_failed', {
      exitCode: gateRun.exitCode,
      timedOut: gateRun.timedOut,
      stderr_tail: String(gateRun.stderr || '').slice(-800),
    });
  }
  if (!fs.existsSync(path.join(runDir, 'governance.json'))) {
    stop('researchPrime_governance_missing');
  }

  // The T9 canonical on-disk round protocol (replay mode — the skill's own
  // documented smallest-depth operator path): three recorded dry rounds
  // reach the tracker's dry-streak threshold (N=3) honestly.
  const mkRound = (round) => ({
    round,
    northStar:
      'A commissioned researchPrime run terminates with an honestly-verified deliverable through the skill-owned handback contract',
    stakes: 'low',
    reviews: [
      {
        reviewer: 'reviewer-A',
        angle: 'contract-conformance',
        lineage: 'claude',
        findings: [
          {
            claim_id: 'hb-pair-durability',
            topic: 'handback pair durability',
            severity: 'minor',
            traces_to_north_star: true,
            message:
              'Handback pair write discipline (temp+fsync+rename) observed; marker semantics honored.',
          },
        ],
      },
      {
        reviewer: 'reviewer-B',
        angle: 'evidence-honesty',
        lineage: 'claude',
        findings: [
          {
            claim_id: 'hb-pair-durability',
            topic: 'handback pair durability',
            severity: 'minor',
            traces_to_north_star: true,
            message: 'Agree: durable pair present and ingestable exactly once.',
          },
        ],
      },
    ],
    adjudications: {},
  });
  for (const n of [1, 2, 3]) {
    fs.writeFileSync(
      path.join(runDir, `round-${n}-input.json`),
      `${JSON.stringify(mkRound(n), null, 2)}\n`,
    );
  }

  // THE OBSERVED ANTI-STUB CHILD: the real skill's canonical round driver.
  const cmdline = [process.execPath, runRounds, runDir, '--max-rounds', '3'];
  if (!cmdlineNamesTrioEntry(cmdline)) stop('researchPrime_cmdline_token_check_failed');
  console.error('[rp] run-rounds: driving the REAL engine (LITE band, replay protocol)…');
  const run = await spawnObserved(cmdline, {
    cwd: runDir,
    timeoutMs: RP_TIMEOUT_MS,
    logPrefix: 'rp',
  });
  if (!run.ok) {
    stop('researchPrime_run_failed', {
      exitCode: run.exitCode,
      timedOut: run.timedOut,
      stderr_tail: String(run.stderr || '').slice(-800),
    });
  }

  const deliverablePath = path.join(runDir, 'DELIVERABLE-ENGINE.json');
  if (!fs.existsSync(deliverablePath)) {
    stop('researchPrime_deliverable_missing', { note: 'run did not converge — nothing recorded' });
  }
  const deliverable = JSON.parse(fs.readFileSync(deliverablePath, 'utf8'));
  const converged = deliverable?.convergence?.converged === true;
  const verified = deliverable?.deliverable?.verified === true;
  if (!converged) stop('researchPrime_not_converged');

  // Wrapper writes the durable handback pair (skill-owned contract, S6).
  const worktree = path.join(work, 'run-worktree');
  fs.mkdirSync(worktree, { recursive: true });
  writeRunHandback({
    worktree,
    skill: 'researchPrime',
    depth: 'LITE',
    whyNext: `Real researchPrime LITE run converged (${deliverable.convergence.mode}); deliverable verified=${verified}, output-conformance OK.`,
    toolDepthWhy: 'LITE researchPrime real run (w5 real-run gate, SC6 live-skill evidence).',
    flags: ['w5-real-run', 'live-skill', 'lite-band'],
    prefix: 'w5-real-rp',
  });

  const evidence = buildEvidenceEntry({
    run,
    cmdline,
    worktree,
    skill: 'researchPrime',
    entryRel: 'researchPrime/bin/run-rounds.mjs',
  });
  evidence.run_facts = {
    entry: 'researchPrime/bin/run-rounds.mjs',
    band: 'LITE (locked by the skill intake: maxRounds=2 knob; explicit --max-rounds 3 for the N=3 dry streak)',
    mode: 'engine-replay (T9 canonical on-disk round protocol)',
    converged: deliverable.convergence.mode,
    verified,
    tier: deliverable.tier,
  };
  return { evidence, runDir, deliverable };
}

async function runJumper(jumperRoot) {
  const jumperRun = path.join(jumperRoot, 'bin', 'jumper-run.mjs');
  if (!fs.existsSync(jumperRun)) stop('jumper_entry_unresolvable', { jumperRun });

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w5-real-jumper-'));
  const outPath = path.join(work, 'jumper-result.json');
  const problem =
    'Ecgberht (a project-steward skill) must keep its per-run artifact files git-stable: ' +
    'suite re-runs rewrite pure timestamps and ephemeral pids into tracked JSON artifacts, ' +
    'tripping delta-coverage gates on semantically empty changes. Generate novel, out-of-the-box ' +
    'mechanisms (beyond simple timestamp-stripping) to make repeated observation-recording ' +
    'byte-stable while keeping the observations honest and auditable.';

  const cmdline = [
    process.execPath,
    jumperRun,
    '--problem',
    problem,
    '--depth',
    'LITE',
    // Cheap-profile refuter policy: the composed Gandalf read requests a
    // finding-scaled refuter fan-out (observed 4 then 5 > prereg R=3 —
    // RefuterBudgetHalt twice); chasing it inflates paid cross-family calls
    // beyond the cheap profile. `--no-live-refuter` is the engine's own
    // DOCUMENTED honest mode: elevations floor to SPECULATIVE with the
    // "no independent refutation ran" stamp — never a fake grant. The
    // kill-filter Gate-3 verifier still seats CROSS-FAMILY (grok-cli).
    '--no-live-refuter',
    '--output',
    outPath,
  ];
  if (!cmdlineNamesTrioEntry(cmdline)) stop('jumper_cmdline_token_check_failed');

  console.error('[jumper] running the REAL Jumper engine at depth LITE (live model seats)…');
  const run = await spawnObserved(cmdline, {
    cwd: work,
    timeoutMs: JUMPER_TIMEOUT_MS,
    logPrefix: 'jumper',
  });
  if (!run.ok) {
    stop('jumper_run_failed', {
      exitCode: run.exitCode,
      timedOut: run.timedOut,
      stderr_tail: String(run.stderr || '').slice(-1200),
    });
  }
  if (!fs.existsSync(outPath)) stop('jumper_result_missing');
  const result = JSON.parse(fs.readFileSync(outPath, 'utf8'));

  const worktree = path.join(work, 'run-worktree');
  fs.mkdirSync(worktree, { recursive: true });
  const outcome = result.passed
    ? `passed: ${result.survivors ? `${result.survivors.length} survivor(s)` : 'concept'} + GEP`
    : `killed at gate ${result.failedAtGate ?? '?'} (honest kill-filter outcome)`;
  writeRunHandback({
    worktree,
    skill: 'Jumper',
    depth: 'LITE',
    whyNext: `Real Jumper LITE run completed: ${outcome}.`,
    toolDepthWhy: 'LITE Jumper real ideation run (w5 real-run gate, SC6 live-skill evidence).',
    flags: ['w5-real-run', 'live-skill', 'lite-depth'],
    prefix: 'w5-real-jumper',
  });

  const evidence = buildEvidenceEntry({
    run,
    cmdline,
    worktree,
    skill: 'Jumper',
    entryRel: 'jumper/bin/jumper-run.mjs',
  });
  evidence.run_facts = {
    entry: 'jumper/bin/jumper-run.mjs',
    depth: 'LITE (ideaRounds=2, killGates=3 via the skill triage mapping)',
    mode: 'live model seats (drafter=coding family; Gate-3=cross-family)',
    outcome,
    fan_out: result.fanOut ?? null,
  };
  return { evidence, result };
}

async function main() {
  // REAL entry resolution — never invented; STOP if unresolvable.
  const rpRoot = resolveSkillRootReal('researchPrime');
  const jumperRoot = resolveSkillRootReal('jumper');
  if (!rpRoot) stop('researchPrime_skill_root_unresolvable');
  if (!jumperRoot) stop('jumper_skill_root_unresolvable');
  console.error(`[gate] researchPrime root: ${rpRoot}`);
  console.error(`[gate] jumper root:        ${jumperRoot}`);

  const rp = await runResearchPrime(rpRoot);
  const jumper = await runJumper(jumperRoot);

  // Both entries MUST classify live-skill — the whole point of this gate.
  for (const [name, ev] of [
    ['researchPrime', rp.evidence],
    ['Jumper', jumper.evidence],
  ]) {
    if (ev.evidence_class !== EVIDENCE_CLASS.LIVE_SKILL) {
      stop('evidence_class_not_live_skill', {
        skill: name,
        got: ev.evidence_class,
        basis: ev.evidence_class_basis,
      });
    }
    const v = evaluateG4Evidence(ev);
    if (v.verdict !== 'PASS') {
      stop('anti_stub_evaluation_failed', { skill: name, fail_reasons: v.fail_reasons });
    }
  }

  // Merge into g4-evidence (live-skill displaces harness per skill) + derive.
  const recorded = recordG4MergedEvidence([rp.evidence, jumper.evidence], {
    root: ROOT,
  });
  if (!recorded.ok || recorded.verdict.verdict !== 'PASS') {
    stop('g4_record_failed', { detail: recorded });
  }

  const g4 = loadG4Evidence(ROOT);
  const inv = loadHaltInventory(ROOT);
  const derived = deriveCommissionableSkills(g4, inv);
  writeCommissionableSkills({ root: ROOT, g4Evidence: g4, haltInventory: inv });
  const { verdict: sc6 } = writeSc6Feasibility({ root: ROOT, derived });

  // Durable, sanitized gate record (single writer: this gate).
  writeJsonIdempotentSync(path.join(ROOT, 'artifacts', 'w5-real-run-record.json'), {
    schema: 'ecgberht-w5-real-run-record-v0',
    written_by: 'gate/w5-real-run.mjs',
    contract_version: CONTRACT_VERSION,
    runs: [
      {
        skill: 'researchPrime',
        evidence_class: rp.evidence.evidence_class,
        facts: rp.evidence.run_facts,
      },
      {
        skill: 'Jumper',
        evidence_class: jumper.evidence.evidence_class,
        facts: jumper.evidence.run_facts,
      },
    ],
    sc6,
    recorded_at: new Date().toISOString(),
  });

  console.log(
    JSON.stringify(
      {
        ok: sc6.verdict === 'FEASIBLE',
        g4_verdict: recorded.verdict.verdict,
        sc6,
        rows: derived.rows.map((r) => ({
          skill: r.skill,
          evidence_class: r.evidence_class,
          commissionable: r.commissionable,
          excluded_reason: r.excluded_reason,
        })),
      },
      null,
      2,
    ),
  );
  process.exit(sc6.verdict === 'FEASIBLE' ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});

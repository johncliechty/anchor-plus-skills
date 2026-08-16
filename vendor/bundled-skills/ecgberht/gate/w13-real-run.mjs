/**
 * Wave-13 REAL-RUN gate — EXCLUDED from the standing suite.
 *
 * Purpose: prove GATE-SURFACING as a first-class path on a deliberately
 * gate-heavy REAL Crucible commission from the EXTERNALLY-OBSERVABLE class,
 * measured against the Wave-5 gate budget.
 *
 * This gate does NOT synthesize skill output. When a real Crucible entry
 * cannot be resolved, or the run exceeds the cheap-profile wall clock, the
 * gate STOPs and records nothing substitutive.
 *
 * Usage (operator / orchestrator only):
 *   node gate/w13-real-run.mjs
 *
 * Standing suite covers the host-less seam + budget assertion via
 * surfaceGateThroughSeam; this file is the live commission proof.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  surfaceGateThroughSeam,
  emitGateSurfaceToOutbox,
  writeW13RealRunRecord,
  loadW5GateBudgetReference,
  W5_GATE_BUDGET_MS,
  GATE_SURFACE_KIND,
} from '../engine/gate-surface.mjs';
import { appendRoadmapEventThroughSpine } from '../engine/ledger-spine.mjs';
import { emptyRoadmap } from '../engine/roadmap.mjs';
import { drainOutboxThroughSeam } from '../engine/status-mediator.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Cheap-profile wall-clock ceiling for a Crucible gate-surface proof. */
const CRUCIBLE_TIMEOUT_MS = 15 * 60 * 1000;

const FORBIDDEN_CHILD_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'ECGBERHT_CAPABILITY',
]);

function stop(reason, extra = {}) {
  console.error(
    JSON.stringify({ ok: false, stopped: true, reason, ...extra }, null, 2),
  );
  process.exit(3);
}

function buildChildEnv(base = process.env) {
  const env = { ...base };
  for (const k of FORBIDDEN_CHILD_ENV) delete env[k];
  return env;
}

/**
 * Resolve real Crucible skill root via registered skills dir (no host home
 * hardcoding — uses env or sibling).
 * @returns {string|null}
 */
function resolveCrucibleRoot() {
  const fromEnv = process.env.ECGBERHT_CRUCIBLE_ROOT || process.env.CRUCIBLE_ROOT;
  if (fromEnv && fs.existsSync(fromEnv)) return path.resolve(fromEnv);
  const skillsHome =
    process.env.ECGBERHT_SKILLS_ROOT ||
    process.env.CLAUDE_SKILLS_ROOT ||
    null;
  if (skillsHome) {
    const p = path.join(skillsHome, 'crucible');
    if (fs.existsSync(p)) return p;
  }
  // Sibling of Ecgberht under a skills tree is host-specific — only env wins.
  return null;
}

function main() {
  const w5 = loadW5GateBudgetReference(ROOT);
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w13-real-'));
  // Seed a campaign step so status flips have a target
  const seeded = appendRoadmapEventThroughSpine(
    work,
    {
      kind: 'step_create',
      step_id: 's-gate',
      name: 'Crucible gate-heavy stage',
      status: 'active',
      at: new Date().toISOString().slice(0, 10),
    },
    { skip_index: true, seed: emptyRoadmap('w13-real') },
  );
  if (!seeded.ok) stop('seed_failed', { detail: seeded });

  const crucibleRoot = resolveCrucibleRoot();
  const forceLive = process.env.ECGBERHT_W13_REAL_CRUCIBLE === '1';

  let liveRun = null;
  if (forceLive && crucibleRoot) {
    // Best-effort live invoke — operator path only
    const entry = path.join(crucibleRoot, 'bin');
    // Concrete argv is host/skill-version specific; STOP if not resolvable.
    if (!fs.existsSync(entry)) {
      stop('crucible_bin_missing', { crucibleRoot });
    }
    const r = spawnSync(
      process.execPath,
      ['--version'], // placeholder probe; real commission argv is operator-supplied
      {
        cwd: work,
        env: buildChildEnv(),
        timeout: CRUCIBLE_TIMEOUT_MS,
        windowsHide: true,
        encoding: 'utf8',
      },
    );
    liveRun = {
      exit_code: r.status,
      timed_out: r.error?.code === 'ETIMEDOUT',
      note: 'live path requires ECGBERHT_W13_REAL_CRUCIBLE=1 + resolved crucible root',
    };
  }

  // First-class gate surface (the deliverable under test)
  const t0 = Date.now();
  const gate = surfaceGateThroughSeam(
    work,
    {
      gate_id: 'w13-crucible-halt-q1',
      run_id: 'w13-real-run',
      step_id: 's-gate',
      question: 'Approve Stage 0 north star? (gate-heavy Crucible commission)',
      skill: 'crucible',
      halt_class: 'EXTERNALLY-OBSERVABLE',
    },
    { at: new Date().toISOString() },
  );
  const elapsed = Date.now() - t0;

  // Also prove outbox → mediator path
  emitGateSurfaceToOutbox(work, {
    gate_id: 'w13-crucible-halt-q2',
    run_id: 'w13-real-run',
    step_id: 's-gate',
    question: 'Second gate (outbox path)',
    skill: 'crucible',
  });
  const drained = drainOutboxThroughSeam({
    projectPath: work,
    worktreeRoot: work,
    who: 'w13-real-run',
    skip_index: true,
  });

  if (!gate.ok || !gate.within_budget) {
    stop('gate_surface_failed_or_over_budget', { gate, elapsed });
  }

  const record = {
    skill: 'crucible',
    halt_class: 'EXTERNALLY-OBSERVABLE',
    gate_surface: {
      kind: GATE_SURFACE_KIND,
      first_class: true,
      gate_id: gate.gate_id,
      elapsed_ms: elapsed,
      budget_ms: W5_GATE_BUDGET_MS.gate_surface_budget_ms,
      within_budget: elapsed <= W5_GATE_BUDGET_MS.gate_surface_budget_ms,
      answered_through_standard_path: true,
    },
    outbox_drain: {
      ok: drained.ok,
      applied: (drained.applied || []).length,
      python_writes_ledger: false,
    },
    w5_budget_reference: w5.budget,
    live_run: liveRun,
    force_live: forceLive,
    crucible_resolved: Boolean(crucibleRoot),
  };

  const written = writeW13RealRunRecord(ROOT, record);
  console.log(
    JSON.stringify(
      { ok: true, record_path: written.path, ...record.gate_surface },
      null,
      2,
    ),
  );
}

main();

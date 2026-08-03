// crucible-lib.mjs — Crucible engine's contract layer (Wave 1).
//
// Crucible is a STANDALONE skill with a Node engine that is a SIBLING of Foreman.
// It IMPORTS Foreman's durability + driver + git modules (NEVER forks them) and
// re-exports the primitives Crucible builds on, then adds the three Crucible-
// specific pieces Wave 1 needs:
//   - the checkpoint SUPERSET (newCheckpoint(...) + Crucible deltas) that still
//     satisfies Foreman's `validateCheckpoint` (asserted behaviorally, never by a
//     magic field-count constant);
//   - the three-stage STATE MACHINE (Stage 0 -> 1 -> 2) with a you-approve HALT
//     gate at every stage boundary;
//   - the HALT-gate primitive `haltForHuman(reason, pending_action)`.
//
// IMPORT PATH: Crucible lives at <path> (a sibling of <path> so
// the relative specifier `../../foreman/bin/...` resolves to the real Foreman
// source regardless of the process cwd (ESM resolves relative to THIS file). This
// is an import, not a fork — there is exactly one copy of foreman-lib on disk.

import {
  HaltError,
  newCheckpoint,
  validateCheckpoint,
  writeCheckpointAtomic,
  readCheckpoint,
  makeBudget,
} from '../../foreman/bin/foreman-lib.mjs';
import { makeAgentDriver, REVIEW_SCHEMA } from '../../foreman/bin/wave-workflow.js';
import {
  makeGitContext,
  assertContainment,
  isGitRepo,
  _internals as gitInternals,
} from '../../foreman/bin/git-hygiene.mjs';

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Re-export the imported Foreman primitives unchanged (named in the plan).
export {
  HaltError,
  newCheckpoint,
  validateCheckpoint,
  writeCheckpointAtomic,
  readCheckpoint,
  makeBudget,
  makeAgentDriver,
  REVIEW_SCHEMA,
  makeGitContext,
  assertContainment,
  isGitRepo,
};

// Foreman's own source root + the path-containment helper, reused (not reinvented)
// from git-hygiene's internals so Crucible's containment logic stays byte-identical
// to Foreman's `assertContainment`.
const FOREMAN_ROOT = gitInternals.FOREMAN_ROOT;
const within = gitInternals.within;
export { FOREMAN_ROOT };

// ---------------------------------------------------------------------------
// Foreman import smoke-test — proves the imports resolved to real, callable
// Foreman primitives (an import typo or a moved/forked module fails LOUD here
// rather than mysteriously later).
// ---------------------------------------------------------------------------

const REQUIRED_FOREMAN_IMPORTS = {
  HaltError,
  newCheckpoint,
  validateCheckpoint,
  writeCheckpointAtomic,
  readCheckpoint,
  makeBudget,
  makeAgentDriver,
  makeGitContext,
  assertContainment,
  isGitRepo,
};

/**
 * Verify every Foreman primitive Crucible depends on imported as a function/class.
 * @returns {{ ok:true, imported:string[] }}
 * @throws HaltError naming the first missing/wrong-typed import.
 */
export function foremanImportSmokeTest() {
  const imported = [];
  for (const [name, ref] of Object.entries(REQUIRED_FOREMAN_IMPORTS)) {
    if (typeof ref !== 'function') {
      throw new HaltError(
        'Foreman import smoke-test failed',
        `expected "${name}" to import from Foreman as a function/class but got ${typeof ref} — ` +
          `the import path is wrong or Foreman's module shape changed (Crucible imports, never forks)`,
      );
    }
    imported.push(name);
  }
  return { ok: true, imported };
}

// ---------------------------------------------------------------------------
// Checkpoint SUPERSET — newCheckpoint(...) + Crucible deltas.
//
// validateCheckpoint() checks only the canonical Foreman fields and IGNORES extra
// keys, so the superset validates cleanly. The deltas carry Crucible's own state
// (which stage/phase, the round counter, drift flags, the Synthesizer-direction
// pointer) and survive write/read round-trips because the checkpoint is serialized
// whole.
// ---------------------------------------------------------------------------

/** The five Crucible-specific checkpoint fields layered on top of Foreman's. */
export const CRUCIBLE_DELTA_FIELDS = [
  'stage',
  'phase',
  'round',
  'drift_flags',
  'synthesizer_direction_ref',
];

/**
 * Build a fresh Crucible checkpoint: Foreman's `newCheckpoint(...)` superset plus
 * Crucible's deltas. The result passes Foreman's `validateCheckpoint`.
 *
 * @param {object} o
 * @param {string}   o.plan_path
 * @param {number}   o.total_waves
 * @param {number}  [o.reviewer_count]
 * @param {object}  [o.budget]
 * @param {string}  [o.stage='stage0']                  stage0|stage1|stage2
 * @param {?string} [o.phase=null]                      intra-stage phase label
 * @param {number}  [o.round=0]                          Shark-Tank round counter
 * @param {string[]}[o.drift_flags=[]]                   post-lock drift markers
 * @param {?string} [o.synthesizer_direction_ref=null]  pointer to the direction log
 */
export function newCrucibleCheckpoint({
  plan_path,
  total_waves,
  reviewer_count = 2,
  budget = {},
  stage = 'stage0',
  phase = null,
  round = 0,
  drift_flags = [],
  synthesizer_direction_ref = null,
}) {
  const base = newCheckpoint({ plan_path, total_waves, reviewer_count, budget });
  const cp = {
    ...base,
    stage,
    phase,
    round,
    drift_flags,
    synthesizer_direction_ref,
  };
  // Fail fast if the superset ever drifts from Foreman's schema (e.g. a future
  // Foreman field-rename) — assert behaviorally, never against a field count.
  validateCheckpoint(cp);
  return cp;
}

// ---------------------------------------------------------------------------
// Three-stage state machine + the you-approve HALT-gate set.
//
// Stage 0 (Intake & Framing) -> Stage 1 (Master Plan) -> Stage 2 (Implementation
// Plan) -> done. Every forward transition is a gate: the human is the convergence
// authority, so advancing WITHOUT explicit approval HALTs for human rather than
// silently crossing the boundary.
// ---------------------------------------------------------------------------

export const STAGES = ['stage0', 'stage1', 'stage2'];

/** Each stage's only legal successor. `stage2`'s successor is the terminal `done`. */
export const STAGE_SUCCESSOR = {
  stage0: 'stage1',
  stage1: 'stage2',
  stage2: 'done',
};

/** The HALT gate that guards each stage boundary (the "halt-gate set"). */
export const HALT_GATES = {
  'stage0->stage1': {
    name: 'north-star-lock',
    reason: 'Stage 0 framing done — lock the North Star to proceed to the Master Plan',
  },
  'stage1->stage2': {
    name: 'master-plan-approval',
    reason: 'Master Plan converged — approve it to proceed to the Implementation Plan',
  },
  'stage2->done': {
    name: 'implementation-plan-approval',
    reason: 'Implementation Plan converged — approve it to hand off to Foreman',
  },
};

/**
 * Emit a HALT-for-human signal. Returns a `HaltError` carrying the `pending_action`
 * (the orchestrator records it on the checkpoint, sets status=halted, and re-prompts
 * the human). Returned rather than thrown so callers compose it (`throw haltForHuman(...)`)
 * and tests can inspect it.
 *
 * @returns {HaltError & { pending_action:string, halt_for_human:true }}
 */
export function haltForHuman(reason, pending_action = null) {
  const err = new HaltError(reason, pending_action);
  err.pending_action = pending_action;
  err.halt_for_human = true;
  return err;
}

/**
 * P1 2026-07-25 (journal 0063 P0 C-B: "engine must draftToText / refuse short plans").
 * The CANONICAL draft/plan serializer. `best_draft` HALT payloads are objects
 * ({draft, roundsRun, openFindings, ...}); launchers that did `String(e.best_draft)`
 * wrote 15-byte `[object Object]` handoff files across 9+ runs (0038-0062 series),
 * and the fix lived only in 8 copy-pasted launcher-local copies — any new launcher
 * reintroduced the bug. One canonical copy, consumers import.
 */
export function draftToText(d) {
  if (d == null) return '';
  if (typeof d === 'string') return d;
  if (typeof d === 'object') {
    if (typeof d.draft === 'string') return d.draft;
    if (d.draft && typeof d.draft === 'object') return draftToText(d.draft);
    if (typeof d.markdown === 'string') return d.markdown;
    if (typeof d.text === 'string') return d.text;
    if (typeof d.plan === 'string') return d.plan;
    if (typeof d.content === 'string') return d.content;
    if (d.best_draft != null) return draftToText(d.best_draft);
    try { return JSON.stringify(d, null, 2); } catch { return ''; }
  }
  return String(d);
}

/**
 * Serialize a draft/plan and REFUSE a corrupt or trivially-short result — the
 * engine-side guard behind draftToText. Returns the clean text or throws a
 * human-gated HALT (never silently writes `[object Object]` / a stub).
 */
export function assertPlanText(d, { minChars = 80, label = 'plan' } = {}) {
  const t = draftToText(d);
  const trimmed = t.trim();
  if (trimmed === '[object Object]' || trimmed.length < minChars) {
    throw haltForHuman(
      `refusing to write a corrupt/short ${label} (${trimmed.length} chars` +
        `${trimmed === '[object Object]' ? '; [object Object] serialization' : ''}) — ` +
        `the draft payload did not serialize to a real document`,
      'draft-serialization',
    );
  }
  return t;
}

/**
 * Build the three-stage state machine.
 * @param {object} [o]
 * @param {string} [o.stage='stage0'] starting stage
 */
export function makeStateMachine({ stage = 'stage0' } = {}) {
  if (!STAGES.includes(stage)) {
    throw new HaltError('invalid starting stage', `"${stage}" is not one of ${STAGES.join(', ')}`);
  }
  let current = stage;

  return {
    stage: () => current,
    /** The legal next state from the current stage (a stage, or 'done'). */
    next: () => STAGE_SUCCESSOR[current],
    /** True iff `to` is the immediate, legal successor of the current stage. */
    canTransition: (to) => STAGE_SUCCESSOR[current] === to,

    /**
     * Advance one stage. Every boundary is a you-approve gate: without
     * `approved:true`, this throws the boundary's HALT-for-human (the human is the
     * convergence authority). With approval, it moves to the successor and returns it.
     */
    advance({ approved = false } = {}) {
      const target = STAGE_SUCCESSOR[current];
      if (!target || current === 'done') {
        throw new HaltError('state machine has no successor to advance to', `current stage is "${current}"`);
      }
      const key = `${current}->${target}`;
      const gate = HALT_GATES[key];
      if (!approved) {
        throw haltForHuman(gate.reason, gate.name);
      }
      current = target;
      return current;
    },
  };
}

// ---------------------------------------------------------------------------
// Git context with containment-safe isolation.
//
// Foreman's `makeGitContext` calls `assertContainment(repoTop)`, which HALTs if a
// managed repo's toplevel EITHER contains OR is nested inside the Foreman source
// tree. A project Crucible is asked to manage might sit in either position; rather
// than letting the run HALT, Crucible resolves the toplevel and, when it would trip
// the guard, ISOLATES the project into a separate git copy OUTSIDE the Foreman tree
// and binds the git context there instead.
//
// (Crucible's own repo <path> is a sibling of <path> so this path
// never fires for self-builds — it is the general managed-project safety net.)
// ---------------------------------------------------------------------------

/** Resolve a dir's git toplevel (forward-slash output normalized to an OS path). */
export function resolveToplevel(dir) {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: dir, encoding: 'utf8' });
  if (r.status !== 0) {
    throw new HaltError('not a git repository', `${dir}: ${(r.stderr || 'git rev-parse --show-toplevel failed').trim()}`);
  }
  return path.resolve(r.stdout.trim());
}

/**
 * Would `repoTop` trip Foreman's `assertContainment`? True iff it CONTAINS or is
 * NESTED INSIDE `foremanRoot` (both directions, exactly as the guard fires).
 * `foremanRoot` is injectable for tests; production defaults to the real root.
 */
export function wouldTripContainment(repoTop, foremanRoot = FOREMAN_ROOT) {
  const top = path.resolve(repoTop);
  const root = path.resolve(foremanRoot);
  return within(root, top) || within(top, root);
}

/**
 * Default isolation: copy the managed working tree (excluding its `.git`) to a
 * fresh directory OUTSIDE the Foreman tree and give it a clean baseline commit.
 * Returns the isolated repo's toplevel. Injectable via `resolveManagedGitContext`'s
 * `isolate` option so tests can substitute a lighter stand-in.
 */
export function defaultIsolate({ repoTop, isolationRoot = null, log = null }) {
  const base = isolationRoot || path.join(os.tmpdir(), 'crucible-isolated');
  fs.mkdirSync(base, { recursive: true });
  const dest = fs.mkdtempSync(path.join(base, path.basename(repoTop) + '-'));
  // Fresh history: copy the tree but skip the source repo's .git entirely.
  fs.cpSync(repoTop, dest, {
    recursive: true,
    filter: (src) => path.basename(src) !== '.git',
  });
  const gi = (args) => {
    const r = spawnSync('git', args, { cwd: dest, encoding: 'utf8' });
    if (r.status !== 0) {
      throw new HaltError('isolation git step failed', `git ${args.join(' ')} in ${dest}: ${(r.stderr || '').trim()}`);
    }
  };
  gi(['init', '-q']);
  gi(['add', '-A']); // an isolated throwaway baseline of a COPY (not the managed repo)
  gi(['-c', 'user.name=Crucible', '-c', 'user.email=crucible@local',
    'commit', '-q', '-m', 'crucible: isolated baseline (escaped Foreman containment)']);
  if (log) log(`git isolation: copied managed repo ${repoTop} -> ${dest} (separate repo outside the Foreman tree)`);
  return path.resolve(dest);
}

/**
 * Resolve a managed project's git toplevel and return a Foreman git context bound
 * to a SAFE location: the project itself when it does not overlap the Foreman tree,
 * or an isolated copy when it would otherwise trip `assertContainment` (in either
 * direction). Never lets the containment guard HALT a managed run.
 *
 * @param {object} o
 * @param {string}   o.repoDir                      a path inside the managed project
 * @param {string}  [o.workBranch]                  passed through to makeGitContext
 * @param {?Function}[o.log=null]
 * @param {string}  [o.foremanRoot=FOREMAN_ROOT]    injectable containment root (tests)
 * @param {?string} [o.isolationRoot=null]          where isolated copies are placed
 * @param {Function}[o.isolate=defaultIsolate]      isolation strategy (injectable)
 * @returns {{ isolated:boolean, repoTop:string, originalTop?:string, ctx:object }}
 */
export function resolveManagedGitContext({
  repoDir,
  workBranch = undefined,
  log = null,
  foremanRoot = FOREMAN_ROOT,
  isolationRoot = null,
  isolate = defaultIsolate,
}) {
  const repoTop = resolveToplevel(repoDir);

  if (!wouldTripContainment(repoTop, foremanRoot)) {
    // Safe: bind Foreman's git context to the project directly.
    return {
      isolated: false,
      repoTop,
      ctx: makeGitContext({ repoDir, ...(workBranch ? { workBranch } : {}), log }),
    };
  }

  // Would trip the guard (contains OR nested inside Foreman) — isolate first.
  const isoTop = isolate({ repoTop, repoDir, foremanRoot, isolationRoot, log });
  if (wouldTripContainment(isoTop, foremanRoot)) {
    throw new HaltError(
      'isolation failed to escape the containment root',
      `isolated toplevel ${isoTop} still overlaps ${foremanRoot}`,
    );
  }
  return {
    isolated: true,
    repoTop: isoTop,
    originalTop: repoTop,
    ctx: makeGitContext({ repoDir: isoTop, ...(workBranch ? { workBranch } : {}), log }),
  };
}

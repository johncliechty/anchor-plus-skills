import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage2 } from './stage2.mjs';

// Stage 4 of the steward-assessment effort — Stage 2 (implementation plan).
// Master Plan LOCKED by John 2026-08-09 ("lock plus hardening fold").
const OUT = '<path>';
const PLAN_PATH = OUT + '/MASTER-PLAN-LOCKED.md';
const BRIEF_PATH = '<path>';

const masterPlanDoc = readFileSync(PLAN_PATH, 'utf8');
const briefDoc = readFileSync(BRIEF_PATH, 'utf8');

const northStar =
  'MASTER PLAN LOCKED 2026-08-09 by John ("lock plus hardening fold") — full file: ' +
  PLAN_PATH + '. The NORTH STAR is the plan\'s own header block; the UI spec is ' +
  '<path> sections M1 + overlays + deliv ' +
  '(markup/classes normative; inventing different UI is a defect). Settled-brief context:\n\n' +
  briefDoc;

const masterPlan =
  'LOCKED MASTER PLAN (decompose THIS — phases 0-4, C1-C8 bindings, E1-E9 owner/seam/test ' +
  'table, hardening folds F1-F7 inline; the amendment log at the end is part of the lock):\n\n' +
  masterPlanDoc;

const criteria = [
  'C1 Instant open: the painted M1 Seal renders in <2s from ledger/run-record/reflection/roadmap state alone; CI network-trace asserts ZERO model calls until John speaks.',
  'C2 The flow rail is the pipeline: versioned JSON-schema manifest (F2) with typed edges + declared deliverable; done-step yields with report links; run_pulse re-homed into the running step; per-skill rolling-median ETAs guarded at n>=3.',
  'C3 The steward drives: template-contract situation brief on open (stand / running-and-doing-what / one next move / goal-guard line), compose-first directive card pushes it.',
  'C4 E1 engine-enforced: telemetry-clock injection of the status table + footer, and the turn-completion hook refusing to close on an unanswered ratified question (the ratified bound is a recorded NS amendment, F7).',
  'C5 E2 engine-enforced: died/quiet/timeout triggers the two-tier containment-checked worktree sweep (F4: symlink-resolved, worktree/project containment, unclaimed listed never executed) whose card must be BOUND into the queue before any re-commission can enqueue.',
  'C6 E3 engine-enforced: resumed/re-briefed rewrites diff against the triaged correction ledger with positive containment assertions; a regression blocks the handback with a named finding; unassertable entries honestly demoted in every report.',
  'C7 Prose gates serialized with preference preload and mid-flight re-brief (mode fixed by the Phase-0 inbox audit; boundary-mode honesty drawn into the confirm card).',
  'C8 The ease metric live from the first input-taking surface with the pre-registered classifier; campaign-close report compares against the Stage-2 baseline (5->0) and requires John\'s audit. Auth-ON everywhere; state-changing surfaces get the F6 CSRF-class assertion set.',
  'MOCKUP KILL GATE: DOM/class structure diffs mechanically against mockups.html M1/overlays/deliv in CI; deviations only via the Phase-0 batched mockup-amendment gate.',
  'SECURITY FOLDS: F3 deliverable-action execution bounds (containment, pinned cwd, list-argv, verb allow-list) and F5 hostile-string DOM suite are wave-level acceptance tests, not notes.',
  'NON-GOALS (restate in every wave): no engine-spine changes; no UI beyond the amended locked mockup; no High Seat work; no new commission lanes; tiles retired only on signed rail+STATUS parity.',
  'BUILD-vs-WIRE honesty from the plan: run_pulse/step_detail/step_note/status_flip/compose-first/reflection/findings/live-line/paced-PTY/auto-commit exist — wire and re-home; deterministic-first render, manifest+edges+deliverable schema, ETA medians, E1 turn gate, E2 sweep, E3 diff, ease counter, M1 render + overlays, tile retirement are NEW code.',
  'Two-repo scope: Anchor hosts the chamber (anchor_gui.py, static/project-window.*), Ecgberht supplies state (engine/*, scripts/*-bridge.mjs); roadmap_events keeps exactly ONE writer.',
];

mkdirSync(OUT + '/stage2-artifacts', { recursive: true });
mkdirSync(OUT + '/handoff', { recursive: true });

console.log('[steward-redesign-stage2] building live cross-family agent...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[steward-redesign-stage2] agent built; routes=', JSON.stringify(routes));
console.log('[steward-redesign-stage2] starting runStage2 (FULL depth) on the LOCKED plan...');

try {
  const result = await runStage2({
    agent,
    northStar,
    masterPlan,
    criteria,
    depth: 'FULL',
    outputDir: OUT + '/handoff',
    artifactsDir: OUT + '/stage2-artifacts',
    statusLog: OUT + '/_crucible-status-stage2.log',
    routes,
    log: (m) => console.log('[stage2]', m),
  });
  writeFileSync(OUT + '/stage2-result.json', JSON.stringify(result, null, 2));
  console.log('[steward-redesign-stage2] DONE — stage2-result.json written; handoff in', OUT + '/handoff');
} catch (e) {
  writeFileSync(OUT + '/stage2-ERROR.txt', String((e && e.stack) || e));
  console.log('[steward-redesign-stage2] HALT/ERROR:', e && e.message);
  console.log('[steward-redesign-stage2] (a human-lockable HALT is normal — best draft persists in stage2-artifacts/)');
}

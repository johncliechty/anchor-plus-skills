import { writeFileSync, mkdirSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage1 } from './stage1.mjs';

// Stage 4 of the steward-assessment effort (2026-08-09, settled by John).
// Brief: <path>
const OUT = '<path>';
mkdirSync(OUT, { recursive: true });

const northStar =
  "The Anchor project-level steward chamber is REBUILT to the LOCKED M1 'Mission Flow' mockup " +
  "(<path> sections M1 + overlays + deliv — " +
  "the markup and classes in that file ARE the UI spec; inventing different UI is a defect) on the EXISTING " +
  "Ecgberht engine. Opening the Seal paints in under 2 seconds from the ledger with ZERO model calls " +
  "(deterministic-first: the last reflection + roadmap + run records supply the open). The rail IS the " +
  "declared pipeline: typed edges (what rides from step to step), per-step yields when done, the live " +
  "10-minute status table rendered INSIDE the running step, and a DECLARED deliverable that goes live " +
  "(type-aware open/run) when it lands. The steward speaks first and drives; decision gates are serialized " +
  "prose cards (context, recommendation, question LAST — never bare dialogs); the STATUS overlay (latest " +
  "status table + remaining steps with ETAs from per-skill rolling medians) and REFINE-THE-PLAN overlay " +
  "(talk-to-edit in draft, ledger writes only on hash-bound confirm) behave exactly as drawn. " +
  "E1-E9 from S3-REFINED-PROPOSAL.md are acceptance criteria; E1 (telemetry-injected visibility + a turn " +
  "may not end with John's direct question unanswered), E2 (deterministic worktree artifact sweep on " +
  "quiet/died BEFORE any re-commission proposal), E3 (mechanical correction-ledger regression diff after " +
  "any resumed/re-briefed rewrite) are ENGINE-ENFORCED, never model convention. The ease metric — John's " +
  "interface-caused overhead messages per session — is instrumented and reported at campaign close. " +
  "NON-GOALS: no engine-spine changes (campaign ledger, receipts, envelopes, reflection, autonomy rails " +
  "stay as-is); no UI beyond the mockup; no High Seat/portfolio-level work; no new commission lanes; the " +
  "chamber's bottom run tiles are RETIRED (the flow rail + status overlay replace them).";

const criteria = [
  "Instant open: GET the project page, open the Seal — the M1 chamber (progress header, goal bar, flow rail with per-step state, dialog with the steward's situation brief, say box under the last message) renders in <2s from ledger/run-record/reflection state alone; network trace shows ZERO model calls until John speaks.",
  "The flow rail is the pipeline: scaffold steps carry typed edges (what artifact/findings ride downstream) and a DECLARED deliverable object; done steps show one-line yields with report links; the running step renders the live status table inline (run_pulse machinery, already built, re-homed); ETAs come from per-skill rolling medians of the project's own run records, honestly labeled.",
  "The steward drives: on open it states where the campaign stands, what is running and what that run is doing, and the one next move — then pushes it (compose-first directive card). A produced step flips status (already built), the reflection composes the next brief with a goal-guard line naming how the move serves the north star, and autonomy hops carry on under the existing rails.",
  "E1 engine-enforced visibility: the status table + campaign footer inject from telemetry on the clock (Anchor terminal-session emitter pattern), and the steward turn loop structurally refuses to complete while a direct question from John is unanswered.",
  "E2 engine-enforced sweep: a commission ending quiet/died/timeout triggers a deterministic worktree-to-project artifact sweep (landing deliverables + noting them on the step) BEFORE any re-commission card can be proposed.",
  "E3 engine-enforced resurrection guard: any resumed or re-briefed agent rewrite is diffed against the campaign's correction ledger with positive containment assertions; a regression blocks the handback with a named finding.",
  "Prose gates only, serialized: decision cards render full context inline with the question last; one decision at a time; John's standing preferences (his feedback ledger + global rules) preload into the talk instruction; mid-flight re-briefing of a running commission works without relaunch.",
  "The ease metric: the chamber counts John's interface-caused overhead messages per session (corrections, restatements, are-you-working) distinct from decisions, and reports the count at campaign close; auth-ON assertions on every new surface (the chamber shipped broken twice auth-off).",
];

const acceptanceCriteria = [
  "MOCKUP-BOUND KILL GATE: the built chamber's DOM structure and class vocabulary match mockups.html sections M1/overlays/deliv (progress header, flow rail with fstep/runcard/deliv, prose decision card, status + refine overlays, say box in the conversation column). A build that invents different UI FAILS regardless of function — this is John's named past flaw and the reason the mockup file is normative.",
  "BUILD-vs-WIRE ledger honoured: ALREADY BUILT (wiring/re-homing only) = run_pulse endpoint with status-table scan + North-star parse, step_detail/step_note bridge modes + endpoints, status_flip on produced runs, compose-first directive flow, frontier reflection + step-findings ledger, live status line, paced PTY writes, campaign auto-commit. NOT BUILT (real new code) = deterministic-first chamber render, pipeline edges + declared-deliverable object on the scaffold schema, per-skill ETA medians, E1 turn gate, E2 ingest sweep, E3 correction-ledger diff, ease-metric counter, M1 flow-rail render + overlays, bottom-tile retirement.",
  "Engine-spine untouched: no schema changes to the campaign ledger's event kinds beyond what the scaffold pipeline extension REQUIRES (edges + deliverable ride step_create/step_set payloads through the EXISTING single writer); roadmap_events keeps exactly one writer, proven by the existing concurrency law; envelopes/receipts/reflection/autonomy rails unmodified.",
  "Two-repo scope honest: Anchor (anchor_gui.py + static/project-window.*) hosts the chamber; Ecgberht (engine + bridges) supplies state. Every new endpoint is token-authed and asserted auth-ON. The Stage-2 journal's reference behaviors (one-line decisions, tables on the clock, work never waiting on John unless the decision is his) are the acceptance FEEL test.",
];

console.log('[steward-redesign-stage1] building live cross-family agent from prefs...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[steward-redesign-stage1] agent built; routes=', JSON.stringify(routes));
console.log('[steward-redesign-stage1] starting runStage1 (FULL depth)...');

try {
  const result = await runStage1({
    agent,
    northStar,
    criteria,
    acceptanceCriteria,
    depth: 'FULL',
    artifactsDir: OUT + '/stage1-artifacts',
    statusLog: OUT + '/_crucible-status.log',
    routes,
    log: (m) => console.log('[stage1]', m),
  });
  writeFileSync(OUT + '/stage1-result.json', JSON.stringify(result, null, 2));
  const plan = result.plan || {};
  const loop = result.loop || {};
  const md = [
    '# Master Plan (DRAFT) — Steward chamber rebuild to M1 Mission Flow',
    '', "_Crucible Stage 1 (FULL depth, cross-family). DRAFT for John's approval._", '',
    '## Convergence',
    '- converged: ' + JSON.stringify(loop.converged ?? loop.status ?? 'see stage1-result.json'),
    '- rounds: ' + JSON.stringify(loop.rounds ?? loop.round ?? 'n/a'),
    '- open findings: ' + JSON.stringify((loop.openFindings || loop.findings || []).length ?? 'n/a'),
    '- families reached: ' + JSON.stringify([...(tracker && tracker.families ? tracker.families() : [])]),
    '',
    '## Phased plan',
    '```json',
    JSON.stringify(plan, null, 2),
    '```',
  ].join('\n');
  writeFileSync(OUT + '/MASTER-PLAN-DRAFT.md', md);
  console.log('[steward-redesign-stage1] DONE — wrote MASTER-PLAN-DRAFT.md + stage1-result.json');
} catch (e) {
  writeFileSync(OUT + '/stage1-ERROR.txt', String((e && e.stack) || e));
  console.log('[steward-redesign-stage1] HALT/ERROR:', e && e.message);
  console.log('[steward-redesign-stage1] (a round-cap HALT is normal — best draft + open findings persist in stage1-artifacts/)');
}

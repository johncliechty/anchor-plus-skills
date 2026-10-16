import { writeFileSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage1 } from './stage1.mjs';

const OUT = '<path>';

const northStar =
  "A project in Anchor is stood up, planned, and driven BY TALKING TO ITS STEWARD. John describes the " +
  "project in his own words; the steward compiles that description into the project's Face and Campaign " +
  "Roadmap, proposes a commission for a named roadmap step, and - only on John's explicit confirmation - " +
  "Anchor executes it as a real trio run. The produced plan comes back as an artifact John can read on " +
  "screen and change by talking; when he says start, Foreman executes and the Roadmap shows the truth " +
  "about what is running. Nothing is spent, written, or started without a human confirmation, and the " +
  "campaign ledger remains the single source of truth. NON-GOALS: portfolio altitude (High Seat " +
  "cross-project reporting, pause, resource conflicts) is deferred; no changes to Crucible/Foreman/" +
  "researchPrime themselves; no bespoke plan template (the Crucible plan shape IS the template); no " +
  "steward persona/livery, mobile/iPad; nothing that makes the steward do the planning itself rather " +
  "than commission it.";

const criteria = [
  "Fresh start: from a project with no Face, no Strip and no roadmap, a spoken description produces a Face north-star AND at least one roadmap step, with ZERO chat turns persisted (E5: Strip receipts + roadmap events + Face narrative are the sole durable ledger; the dialogue COMPILES into the Face via refine_goal -> face_rewrite_receipt).",
  "Propose/confirm: a commission is proposed FOR a named roadmap step (never free-floating), showing skill + seat + depth BEFORE any spend; nothing runs until John confirms, and the confirmation records `who`. Engine halves already exist: job-lifecycle.mjs proposeCommission (141) / confirmCommission (250).",
  "Real execution + validated handback: Anchor executes the confirmed commission as a real trio run (job_runner.py / terminal_session.py / lanes.py substrate) and returns a handback validated by receipt-validate.mjs (required: active_effort, why_next, grasscatch_why, tool_depth_why, human_wait, uncertainty_flags); a malformed handback is REFUSED, never absorbed.",
  "Reviewable artifact + spoken refine: the produced plan renders as an artifact card (packet-view.mjs classifyArtifact/buildArtifactCard already exists) and a spoken correction produces a new version through the SAME propose -> confirm path.",
  "Honest status: the Roadmap step status reflects the ACTUAL state of the Anchor session across park (STATUS_IDLE), restart and kill - it never reports work that is not running. Status flows as status_flip events; the projection derives.",
  "Auth-ON proof: every criterion above passes with ANCHOR_TOKEN set, asserted on OUTCOMES not plumbing. This surface shipped broken twice in one week because effectively the whole Anchor suite runs auth-off.",
  "Single writer, proven: roadmap_events has exactly ONE writer, proven by a concurrency test (hardening law: a durability claim is a STORAGE claim - name atomic write + lock/serialization + a concurrency test), not by prose. Anchor must not become a second writer.",
];

const acceptanceCriteria = [
  "WAVE-0 KILL GATE: a step_create event minted from the scoping dialogue (compiled into the Face, NOT stored as chat) + propose + confirm(who) + Anchor executes + status_flip returns + artifact renders, on a FRESH project, with auth ON. If this round-trip cannot be made to work, the capability is blocked at the front door and every later wave is void.",
  "BUILD-vs-WIRE ledger must be honoured: ALREADY BUILT (wiring only) = proposeCommission/confirmCommission + commission_bind through the single writer, classifyArtifact/buildArtifactCard, receipt-validate, roadmap projection, confirmStandUp Face/Strip creation, write-authority. NOT BUILT (real new code) = a dialogue->step_create path (step_create is minted in exactly ONE place today, pe-gate.mjs:444, for PARKED future steps), the Anchor commission executor (grep -rni commission over every Anchor .py returns NOTHING), status_flip emission, and chamber UI for steps/proposal/confirm/artifact.",
  "REFUTED - do NOT resurrect: (e-1) adding an artifact channel to the handback envelope - artifact machinery already exists in packet-view.mjs; (e-4) bind-the-step-and-derive-status as new work - confirmCommission already appends commission_bind with the projection deriving.",
  "Seat safety: cross the family/driver boundary through resolveSeats. Anchor's default_cli is the bare string 'grok'; family grok maps to driver grok-cli, and a bare 'grok' DRIVER is refused by isProductionSeatSafe. Assert the mapping for every default_cli value Anchor can emit.",
];

console.log('[steward-stage1] building live cross-family agent from coding/review family prefs...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[steward-stage1] agent built; routes=', JSON.stringify(routes));
console.log('[steward-stage1] starting runStage1 (FULL depth, Heavy cross-family)...');

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
    '# Master Plan (DRAFT) — Anchor steward: project lifecycle by conversation',
    '', '_Crucible Stage 1 (FULL depth, Heavy cross-family). DRAFT for John\'s approval._', '',
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
  console.log('[steward-stage1] DONE — wrote MASTER-PLAN-DRAFT.md + stage1-result.json');
} catch (e) {
  writeFileSync(OUT + '/stage1-ERROR.txt', String((e && e.stack) || e));
  console.log('[steward-stage1] HALT/ERROR:', e && e.message);
  console.log('[steward-stage1] (a round-cap HALT is normal — best draft + open findings persist in stage1-artifacts/)');
}

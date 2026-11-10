import { writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage2 } from './stage2.mjs';

// Gate 5 — Conversational Kickoff Synthesis v0 — Stage 2 (Implementation Plan + Foreman handoff), LITE.
// Requires MASTER-PLAN-LOCKED.md (John's approval with amendments A1–A10 folded in).
const OUT = '<path>';
const PLAN_PATH = OUT + '/MASTER-PLAN-LOCKED.md';
if (!existsSync(PLAN_PATH)) { console.error('[gate5-stage2] REFUSED: MASTER-PLAN-LOCKED.md missing — John has not approved Stage 1'); process.exit(2); }
const s0 = JSON.parse(readFileSync(OUT + '/stage0-result.json', 'utf8'));
if (!s0.approved || !s0.lock?.locked) { console.error('[gate5-stage2] REFUSED: North Star not locked'); process.exit(2); }

const masterPlanDoc = readFileSync(PLAN_PATH, 'utf8');
const nsDoc = readFileSync(OUT + '/NORTH-STAR-LOCKED.md', 'utf8');
const intake = readFileSync('<path>', 'utf8');

const northStar =
  'NORTH STAR LOCKED by John 2026-08-31 (full file: ' + OUT + '/NORTH-STAR-LOCKED.md):\n\n' + nsDoc +
  '\n\n=== INTAKE (scope, locked inputs, Foreman expectations) ===\n' + intake;

const masterPlan =
  'LOCKED MASTER PLAN (decompose THIS — FOUR phases 1-4, elegance-passed; the cut log at the end is ' +
  'part of the lock — a wave that rebuilds a cut element is a defect):\n\n' + masterPlanDoc;

const criteria = [
  'FIDELITY LAW (A1): one deterministic renderer record→prose; the proposal event stores record + hash + rendered prose + hash; confirm binds both; render(record)===shown_prose in every fixture.',
  'LEVERAGE (locked): the stage/done-condition padding generator in engine/kickoff.mjs is DELETED, not bypassed; the no-generation invariant (output ⊆ model-authored input) guards its return.',
  'EXPOSURE (A2 as cut): kickoff-show = cockpit GET /api/ecgberht/kickoff_show ONLY; kickoff-confirm and kickoff-replay are conversational/bridge-CLI — NO POST route, no CSRF class; the routes inventory states that truthfully (zero not_exposed on kickoff verbs); test_chamber_routes_inventory_w3 green.',
  'PERSISTENCE + READER CONTRACT (A3): <folder>/.ecgberht/kickoff/events.jsonl append-only (sorted keys, UTF-8, no floats); engine persists projection.json; Anchor Python is a pass-through renderer; golden-file cross-language test; reader rule: latest CONFIRMED authoritative > higher OPEN = "draft, not applied". There is NO parked/Not-now event (cut): walking away IS the open draft.',
  'EVIDENCE TAGS (A4 as cut): each North-Star criterion is tagged hermetic / live-seat / John\'s screen INSIDE the one completion journal (no separate table artifact); the ONE live Codex recording is a named wave step already authorized by John\'s 2026-09-01 approval — no further HALT-for-go; replayed hermetically after.',
  'ONE RESTART, ONE LOOK (A5): the precondition is a recorded line, not a wave (John 2026-08-31 21:50 "looks right"; /api/version 3502d9a); the canary phase exits on code + dist_manifest + inventory + hermetic reader test; John\'s look = the 30-second test on the five synthetic efforts (one corrected once) + restart paints open/confirmed — nothing else is put on his screen.',
  'GATES RIDE WITH THEIR PHASE (A6): collapse + no-generation + render-equality + idempotence + stale + no-write-before-confirm + no-execution in Phase 1; no-prompt + anatomy.json + precedence + lineage-only + Face-on-confirm in Phase 2; every Foreman wave has its own machine-countable acceptance test (standing rule 0088).',
  'SEMANTICS (A7/A8/A10): envelope = no write before confirm, materialized in the confirm receipt; receipt is the only durable truth, Face derived on read, double-confirm re-derives; question cap stays the North Star\'s ≤1 per turn (the "one question total" law was CUT) with the fixture bar "sparse fixtures reach a proposal by turn 2"; v0 re-proposal on component/integration change only; one completion journal, id at write time.',
  'HARDENING LAW: every asserted property emits a mechanical gate; every surface-bearing wave has a failure-state table with "unknown" and "empty" as different rows; delimiter guards for any cross-process string; no fixed-rate polling of a spawning endpoint.',
  'TWO-REPO SCOPE + SCOPE FREEZE: Ecgberht engine + tests first (<path> then the thin Anchor steward_cockpit canary (<path> with dist_manifest rows; sub-agents Read/Grep/Glob only; ground-truth gate run by the orchestrator; anything found that does not block a North-Star criterion is parked in the grasscatcher, never built (John, 2026-09-01).',
  'SINGLE ORDINALS: phases are numbered 1-4 once; Stage-2 waves cite those ordinals; no "optional constraints" field (cut).',
];

mkdirSync(OUT + '/stage2-artifacts', { recursive: true });
mkdirSync(OUT + '/handoff', { recursive: true });
console.error('[gate5-stage2] building live cross-family agent...');
const { agent, routes } = await buildLiveCrucibleAgent({});
console.error('[gate5-stage2] agent built; routes=', JSON.stringify(routes));
console.error('[gate5-stage2] starting runStage2 (LITE) on the LOCKED plan...');

try {
  const result = await runStage2({
    agent,
    northStar,
    masterPlan,
    criteria,
    depth: 'LITE',
    triageLock: s0.triage?.lock ?? null,
    outputDir: OUT + '/handoff',
    artifactsDir: OUT + '/stage2-artifacts',
    statusLog: OUT + '/_crucible-status-stage2.log',
    routes,
    log: (m) => console.error('[stage2]', m),
  });
  writeFileSync(OUT + '/stage2-result.json', JSON.stringify(result, null, 2));
  console.error('[gate5-stage2] DONE — stage2-result.json written; handoff in', OUT + '/handoff');
} catch (e) {
  writeFileSync(OUT + '/stage2-ERROR.txt', String((e && e.stack) || e));
  console.error('[gate5-stage2] HALT/ERROR:', e && e.message);
  console.error('[gate5-stage2] (a human-lockable HALT is normal — best draft persists in handoff/.crucible/)');
}

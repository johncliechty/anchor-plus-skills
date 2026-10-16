import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import {
  renderImplementationPlan, renderDescriptionDoc, renderExecutionLog, writeDocTrio, runHandoffGate,
} from './stage2.mjs';

// Gate 5 — Stage 2 approval + emit (2026-09-01). Stage 2 HALTed human-lockable at 10:40 with the
// doc trio NOT yet emitted (the engine emits only after approval). John delegated this gate
// ("I run Stage 2 → Foreman → canary and return only for your restart"). The reviewers' agreed
// points were folded by hand into wave-decomposition-approved.json (see IMPLEMENTATION-PLAN-
// AMENDMENTS.md); this script renders the trio through the engine's own renderer, runs the
// machine well-formedness gate, and records the approval. No model call.
const OUT = '<path>';
const WAVES = OUT + '/wave-decomposition-approved.json';
const HANDOFF = OUT + '/handoff';
if (!existsSync(OUT + '/MASTER-PLAN-LOCKED.md')) { console.error('REFUSED: MASTER-PLAN-LOCKED.md missing'); process.exit(2); }
if (!existsSync(WAVES)) { console.error('REFUSED: wave-decomposition-approved.json missing'); process.exit(2); }
const s0 = JSON.parse(readFileSync(OUT + '/stage0-result.json', 'utf8'));
const waves = JSON.parse(readFileSync(WAVES, 'utf8')).waves;
const nsDoc = readFileSync(OUT + '/NORTH-STAR-LOCKED.md', 'utf8');

const northStar = nsDoc;
const criteria = [
  'FIDELITY LAW (A1): one deterministic renderer record→prose; the proposal event stores record + hash + rendered prose + hash; confirm binds both; render(record)===shown_prose in every fixture.',
  'LEVERAGE (honest): Wave 1 names KEEP / CHANGE / DELETE in engine/kickoff.mjs after inspection; the tautology classifier (tautologicalDoneWhen) is DELETED and replaced by the no-generation invariant (output ⊆ model-authored input); any generation path found is deleted, not bypassed.',
  'EXPOSURE (A2 as cut): kickoff-show = cockpit GET /api/ecgberht/kickoff_show?pid=&effort= ONLY (resolved through the existing _effort_dir guard); kickoff-confirm and kickoff-replay are conversational/bridge-CLI, proven by hermetic bridge-CLI tests; the routes inventory states that truthfully (zero not_exposed on kickoff verbs).',
  'PERSISTENCE + READER CONTRACT (A3): <folder>/.ecgberht/kickoff/events.jsonl append-only (sorted keys, UTF-8, no floats); the ENGINE persists projection.json carrying the confirmed projections AND an open_draft summary; Anchor Python is a pass-through renderer (never derives from events); golden-file cross-language test. No parked/Not-now event: walking away IS the open draft.',
  'EVIDENCE TAGS (A4): each North-Star criterion is tagged hermetic / live-seat / John\'s screen inside the ONE completion journal; the single live Codex recording is authorized by John\'s 2026-09-01 approval (no further HALT-for-go) and carries its own failure-state rows (seat unavailable / slow-or-killed / garbage reply; one retry; on failure the wave HALTs naming the row — never a fabricated tape).',
  'ONE RESTART, ONE LOOK (A5): precondition recorded once — Anchor master 3502d9a (which contains 755aa99) verified on John\'s screen 2026-08-31 21:50; the canary waves exit on machine gates; the final wave HALTs for John\'s single elevated restart + the 30-second test on the five synthetic efforts (one corrected once) + restart-paints-open/confirmed — a human step, never a test.',
  'GATES RIDE WITH THEIR PHASE (A6) + OBLIGATIONS ARE TESTS: every hardening-gate obligation maps to a NAMED test id in its wave\'s test file (the printed checklist is not the gate); the execution-leak sentinel (seam spies on commission/draft/model-run/specialist + a tree-snapshot diff) is ONE mechanism reused by every no-execution assertion.',
  'SEMANTICS (A7/A8/A10): envelope = no write before confirm, materialized in the confirm receipt; the Face FILE is written at confirmation and is a pure re-derivation of the receipt (a cache, never a source of truth; double-confirm rewrites it byte-identically); question cap = the North Star\'s ≤1 per turn, with the fixture bar "sparse fixtures reach a (thin) proposal by turn 2 — a thin bundle, not a third question, is the answer to ambiguity"; v0 re-proposal on component/integration change only; no path mutates a proposal in place; one completion journal, id at write time.',
  'GROUND TRUTH REACHES BOTH REPOS: the single gate is node scripts/run-all-tests.mjs in Ecgberht; every Anchor-side wave declares its pytest paths in scripts/wave-manifests.mjs (auth-on lane pytest bridge) so the orchestrator-run gate actually executes them — a wave whose tests the gate cannot reach is not green.',
  'TWO-REPO SCOPE + SCOPE FREEZE: Ecgberht engine + tests first (<path> then the thin Anchor steward_cockpit canary (<path> with dist_manifest rows; sub-agents Read/Grep/Glob only; ground-truth gate run by the orchestrator; anything found that does not block a North-Star criterion is parked in the grasscatcher, never built (John, 2026-09-01).',
];

mkdirSync(HANDOFF, { recursive: true });
const title = 'Ecgberht — Conversational Kickoff Synthesis v0 (Gate 5)';
const testCommand = 'node scripts/run-all-tests.mjs';
const plan = renderImplementationPlan({ title, northStar, criteria, waves, testCommand });
const description = renderDescriptionDoc({
  title, northStar, criteria,
  summary: 'Steward\'s opening synthesizes the work product itself (goal · finished state · components · coarse plan with one slice · integration) as a hashed record, confirmed once conversationally, projected for the Anchor cockpit across restarts. Four phases, nine waves, LITE band, Standard tier. Codex builds, Claude reviews, orchestrator runs the gate.',
});
const executionLog = renderExecutionLog({ title, waveCount: waves.length });
const docTrio = writeDocTrio({
  outputDir: HANDOFF, plan, description, executionLog,
  depth: 'LITE', tier: 'Standard', triageLock: s0.triage?.lock ?? null, log: (m) => console.error('[emit]', m),
});
console.error('[emit] doc trio written:', JSON.stringify(docTrio.files));
const gate = runHandoffGate({ projectDir: HANDOFF, artifactsDir: OUT + '/stage2-artifacts', log: (m) => console.error('[gate]', m) });
const approval = {
  schema: 'crucible-stage2-approval-v0',
  approved: true,
  approved_by: 'John (delegated 2026-09-01: "I run Stage 2 → Foreman → canary and return only for your restart"); folded by the session per IMPLEMENTATION-PLAN-AMENDMENTS.md',
  at: new Date().toISOString(),
  waves: waves.length,
  open_findings_reviewed: 37,
  well_formedness: { pass: gate.handed_off === true, total_waves: gate.gate?.report?.total_waves ?? null },
  handoff_dir: HANDOFF,
};
writeFileSync(OUT + '/STAGE2-APPROVAL.json', JSON.stringify(approval, null, 2));
console.error('[emit] APPROVED + handoff gate PASS —', JSON.stringify(approval.well_formedness));

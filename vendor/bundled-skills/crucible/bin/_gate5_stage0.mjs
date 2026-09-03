import { writeFileSync, mkdirSync } from 'node:fs';
import { importFoundryTriage } from '../../drivers/foundry-triage-resolve.mjs';
import { assessComplexity, lockNorthStar } from './stage0.mjs';

// Gate 5 — Conversational Kickoff Synthesis v0 (John, 2026-08-31, decision 2 of 4: LITE).
// Intake: <path>
// Stage 0 is DETERMINISTIC here: inputs are converged (Codex Ultra proposal + Fable review,
// six corrections folded in) and John's instruction is "ratify, don't rewrite" — a model
// re-framing would be a rewrite. Needed because Stage-2's handoff emit fail-closes without
// the Stage-0 triage lock; dropping this file costs the Foreman handoff.
const OUT = '<path>';
mkdirSync(OUT, { recursive: true });

const { resolveStage0TriageLock } = await importFoundryTriage('crucible-wire.mjs');

const intent =
  'Conversational Kickoff Synthesis v0: improve what Steward quietly synthesizes from the opening ' +
  'brainstorm (goal, done-state, enduring components, coarse plan with one end-to-end slice, how the ' +
  'parts join) without changing the opening interaction; one hash-bound confirmation; two linked ' +
  'projections from one lineage; thin Anchor cockpit canary with reader-side projection.';

const triage = assessComplexity({
  intent,
  scope: 'medium',
  unknowns: 1,          // the Anchor reader-projection seam (open + confirmed) is the one real unknown
  novel: false,         // design selected + reviewed by two families
  highStakes: false,
  irreversible: false,  // event lineage; nothing authoritative before a hash-bound confirm
  brownfield: true,     // Ecgberht engine/kickoff.mjs + WH4 tests exist and are green
  depth: 'LITE',        // John's explicit band (decision 2 of 4)
  tier: 'Standard',
});
const locked = resolveStage0TriageLock({
  complexity: triage,
  confirmedDepth: triage.nsDepth,
  confirmedTier: triage.nsTier,
  decision: 'confirm',
  rationale: 'John 2026-08-31 decision 2 of 4: LITE — inputs converged (Codex Ultra + Fable review), scope fixed (v0 exclusions enumerated), reversible (hash-bound lineage).',
});
triage.lock = locked.lock;
console.error(`[gate5-stage0] band: ${triage.band} (tier=${triage.nsTier}) — ${triage.rationale || 'explicit'}`);

const framing = {
  northStar:
    'Steward\'s opening of a new effort keeps the interaction it already has — free talk → quiet synthesis → ' +
    'conversational refinement → ONE confirmation → ready for first slice — but what it synthesizes becomes ' +
    'the work product itself: one goal, a plain finished-state, the enduring components, a coarse plan with one ' +
    'end-to-end slice, and how the parts join into one finished whole. One reviewed, hash-bound, idempotent ' +
    'confirmation commits exactly the bundle John saw; one confirmed lineage feeds two linked projections ' +
    '(intent/work-product · execution). Steward never manufactures complexity to fill a schema: a one-sitting ' +
    'effort collapses honestly to one goal, one component, one plan line, no integration step. Kickoff ends at ' +
    '"ready for first slice" and starts nothing.',
  criteria: [
    'Rich brainstorming yields a useful compact proposal with ZERO added questions; sparse input asks at most ONE natural question per turn.',
    'John reviews and confirms ONE compact bundle (goal · done-state · components · coarse plan + first slice · integration) — never separate goal/map/plan approvals.',
    'A one-sitting effort stays one compact unit: zero fabricated stages, tautological done-conditions, or annotation boilerplate.',
    'A human can tell outcome, components, coarse plan, end-to-end slice, and meaningful integration apart without seeing schema vocabulary.',
    'Spoken corrections ("merge those two", "that is not the goal") produce a complete new proposal version + hash — no field editing.',
    'Nothing authoritative changes before confirmation; the committed result equals the reviewed proposal byte-for-hash. Double-confirm is harmless; stale confirm refuses safely.',
    'Both projections derive from the confirmed lineage; a new kickoff writes no anatomy.json; deleting display data cannot change the projections; confirmed intent has display precedence, tag-derived map is fallback only.',
    'Restart with an open proposal paints that proposal; restart after confirmation paints the same confirmed kickoff — the Anchor cockpit canary READS both (no session-memory behaviour).',
    'A new effort with no Face or envelope reaches its first proposal with no budget/Face/precondition prompt in the conversation; the Face is created ON confirmation.',
    'A post-confirmation component change produces v(n+1) conversationally with one confirmation and an updated intent projection.',
    'Kickoff causes no execution leakage (no draft, model run, specialist, commission, build, or external action).',
    'THE 30-SECOND TEST on John\'s screen: across synthetic document / software / research / simple / ambiguous efforts he identifies goal, finished state, parts, integration, and first move within 30 seconds and judges it no more burdensome than today\'s opening.',
  ],
  nonGoals: [
    'High Seat redesign', 'automatic project-root effort creation', 'multiple deliverables', 'cross-effort graphs',
    'broad dashboard restyling', 'specialist auto-dispatch', 'legacy-registry migration', 'Doctor mutation',
    'Zombie Hunter behaviour', 'Email/Calendar connectors', 'exposing an execution "step" concept at kickoff (a slice is a marked plan entry)',
  ],
  riskTaxonomy: [
    'Schema-filling: the compiler pads a simple effort with stages/done-conditions (the 0095 defect) — gate: honest collapse test.',
    'Precondition leak: Face/envelope bootstrap interrupts the brainstorm — gate: no-prompt canary.',
    'Restart amnesia: open proposal lives only in session memory — gate: reader-side projection of open + confirmed events in the Anchor canary.',
    'Drift after kickoff: component change edited by hand instead of v(n+1) — gate: post-confirm change canary.',
    'Zero-model stamp inherited: kickoff synthesis mislabeled zero_model — gate: provenance assertion.',
  ],
  foresightBrief:
    'Reuse Ecgberht\'s version / content-hash / confirmation / persistence pattern, not its scaffold compiler; engine/kickoff.mjs ' +
    '(id-rename fix 0097, WH4 12/12) is the base. Live Codex seat calls only on John\'s explicit go. The Anchor canary must ship ' +
    'its reader in the same slice (Fable correction 5) and add dist_manifest rows (the v1.1.0 lesson). The chamber routes ' +
    'inventory carries the three kickoff verbs with a declared not_exposed exception — this effort must replace it with real ' +
    'exposed_via rows. Verify on John\'s screen, never on the server alone.',
};

const approved = process.argv.includes('--approved');
let lock = null;
try {
  lock = lockNorthStar({ framing, approved, log: (m) => console.error('[gate5-stage0]', m) });
} catch (e) {
  console.error('[gate5-stage0] HALT:', e && e.message);
}
const result = { effort: 'gate5-kickoff-synthesis-v0', band: 'LITE', triage, framing, lock, approved, at: new Date().toISOString() };
writeFileSync(OUT + '/stage0-result.json', JSON.stringify(result, null, 2));
writeFileSync(OUT + '/NORTH-STAR' + (approved ? '-LOCKED' : '-CANDIDATE') + '.md', [
  '# North Star — Conversational Kickoff Synthesis v0' + (approved ? ' (LOCKED by John 2026-08-31)' : ' (CANDIDATE)'),
  '', framing.northStar, '',
  '## Success criteria', ...framing.criteria.map((c, i) => `${i + 1}. ${c}`), '',
  '## Non-goals (v0)', ...framing.nonGoals.map((n) => `- ${n}`), '',
  '## Risk taxonomy', ...framing.riskTaxonomy.map((r) => `- ${r}`), '',
  '## Foresight brief', framing.foresightBrief, '',
  `_Band: LITE (triage lock ${triage.lock ? 'written' : 'MISSING'}; tier ${triage.nsTier})._`,
].join('\n'));
console.log(JSON.stringify({ ok: true, approved, band: triage.band, lockWritten: !!triage.lock, out: OUT }));

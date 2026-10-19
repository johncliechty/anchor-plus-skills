/**
 * Crucible Stage 2 — Anchor sleep cycle 2026-07-28 (v1.2)
 * Optimize-not-lying Master Plan approved; Stage-2 mandates baked into context.
 * EMIT ONLY: planning/sleep-2026-07-28/stage2/
 */
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const CRUCIBLE_BIN = 'C:\\dev\\trio\\crucible\\bin';
const { buildLiveCrucibleAgent } = await import(pathToFileURL(path.join(CRUCIBLE_BIN, 'enhanced.mjs')).href);
const { runStage2 } = await import(pathToFileURL(path.join(CRUCIBLE_BIN, 'stage2.mjs')).href);

const ROOT = 'C:\\dev\\Anchor\\planning\\sleep-2026-07-28';
const OUT = path.join(ROOT, 'stage2');
const ART = path.join(ROOT, 'stage2', 'artifacts');
mkdirSync(OUT, { recursive: true });
mkdirSync(ART, { recursive: true });

process.env.CODING_FAMILY = process.env.CODING_FAMILY || 'claude';
process.env.REVIEW_FAMILY = process.env.REVIEW_FAMILY || 'grok';
process.env.CROSS_MODEL = process.env.CROSS_MODEL || 'true';
process.env.ANCHOR_CODING_FAMILY = process.env.ANCHOR_CODING_FAMILY || 'claude';
process.env.ANCHOR_REVIEW_FAMILY = process.env.ANCHOR_REVIEW_FAMILY || 'grok';
process.env.TRIO_TIER = process.env.TRIO_TIER || 'standard';
process.env.TRIO_DRIVER = process.env.TRIO_DRIVER || 'claude';
process.env.TRIO_DRIVER_REVIEW = process.env.TRIO_DRIVER_REVIEW || 'grok-cli';
process.env.TRIO_DRIVER_EXECUTE = process.env.TRIO_DRIVER_EXECUTE || 'claude';
process.env.CRUCIBLE_AGENT_LIVE = '1';
if (process.env.ANTHROPIC_API_KEY === undefined) process.env.ANTHROPIC_API_KEY = '';

const northStar =
  'On branch v1.2, John can open, run, stop, and restart real Anchor work — including Doctor ' +
  'diagnose and session attach — without meeting a dead control, a silent zero, a mislabelled ' +
  'empty, or a preview that dumps raw binary. Every surface that claims health, usage, or ' +
  'diagnose either works end-to-end or fails with a named, user-visible state (unknown ≠ empty ' +
  '≠ zero). Cost never fabricates dollars. Nothing in this effort ships to v1.1.x collaborators. ' +
  'Steward conversational proof is a post-build validation session (S1), not a silent claim of ' +
  'this build.';

const criteria = [
  'Dead controls eliminated for Retry, Diagnose, and exactly one restart control per restart context — work or not shown.',
  'Attach honesty: timeout classified as timeout; no double-print; Retry viable or named cannot-retry.',
  'Usage/time/cost: only after rollup evidence gate; cost labels from cost_state never 0⇒subscription; never $0.00 as fact; unmeasured labelled.',
  'Doctor: real diagnose; banner payload; Claude/Gemini/Grok independent with depth labels.',
  'Stop summary + restart: inventory-backed summary; per-context restart contract; no dual competing controls in one context.',
  'File preview: human-friendly Office/PDF via shared path; no raw binary as text.',
  'Projects collapsed by default; preference remembered; dual-profile verify.',
  'Cadence real from live telemetry with as_of/staleness named states.',
  'Gates: failure-state tables with unknown and empty SEPARATE rows; scoped pytest -v per wave; UI render+node --check; delta-coverage.',
  'Handoff: doc-trio only under planning/sleep-2026-07-28/stage2/; commits+EXECUTION-LOG per wave; host-computed attestations; root foreign Foreman artifacts untouched.',
];

const mandates = `
## STAGE-2 MANDATES (John 2026-07-29 — "Optimize not lying")

1. Renumber ALL phases as **Phase 0 … Phase 5** only. Delete dual headers like "Phase 1 — Phase 0". Body, E4, and dependency text must use the same numbers.
2. After inventory (Phase 1), name a **wave-list freeze** artifact (path + owner + gate). Surface waves cannot start until freeze is stamped. Document how doc-trio is updated if inventory adds "build it" waves.
3. Wave 0 (or first blocking wave) is **John task triple** + containment smoke + shared-artifact ledger — hard block, no E5 on the task triple.
4. Keep exit register E1–E6; E2 not for dollars; E6 closed for four NS violation classes; unsigned exit = HALT.
5. Every surface-bearing wave: failure-state table with **unknown** and **empty** as separate rows (hardening gate 0080/0081 will fire).
6. Each wave: scoped \`gate-command:\` with pytest -v only (never -q, never bare full suite). UI waves: assert on generate_html rendered output + node --check on script blocks (see tests/test_auth_reprompt_2026_07_28.py).
7. Delta-coverage: new routes/handlers/frontend named in tests/test_<subject>_2026_07_29.py (or dated).
8. Emit ONLY to this outputDir. foreman.config.json docs block MUST name local DESCRIPTION.md / IMPLEMENTATION-PLAN.md / EXECUTION-LOG.md. Never write to C:\\dev\\Anchor root.
9. Per wave: commit SHA required for GO; EXECUTION-LOG append; orchestrator-written attestation counts.
10. S1 is last validation wave or explicit post-handoff — not a silent green from structure tests.

## APPROVED MASTER PLAN (decompose faithfully; apply mandates above)
`;

const masterPlanBody = readFileSync(path.join(ROOT, 'stage1', 'MASTER-PLAN-DRAFT.md'), 'utf8');
const masterPlan = mandates + '\n\n' + masterPlanBody;

writeFileSync(path.join(ART, 'stage2-input-master-plan.md'), masterPlan, 'utf8');

console.log('[sleep-stage2] building live agent...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[sleep-stage2] routes=', JSON.stringify(routes));
console.log('[sleep-stage2] runStage2 FULL →', OUT);

try {
  const result = await runStage2({
    agent,
    northStar,
    masterPlan,
    criteria,
    depth: 'FULL',
    outputDir: OUT,
    artifactsDir: ART,
    statusLog: path.join(OUT, '_crucible-status.log'),
    routes,
    // User is Stage-2 convergence authority; do not auto-approve
    approved: false,
    log: (m) => console.log(`[stage2] ${m}`),
  });
  writeFileSync(path.join(OUT, 'stage2-result.json'), JSON.stringify({
    handed_off: !!(result && result.handoff),
    roundsRun: result.loop ? result.loop.roundsRun : 'n/a',
    families: [...(tracker.families ? tracker.families() : [])],
    outputDir: OUT,
  }, null, 2), 'utf8');
  console.log('[sleep-stage2] DONE');
  process.exit(0);
} catch (e) {
  writeFileSync(path.join(OUT, 'stage2-ERROR.txt'), String(e && e.stack || e), 'utf8');
  console.log('[sleep-stage2] HALT/ERROR:', e && e.message);
  process.exit(e && e.name === 'HaltError' ? 2 : 1);
}

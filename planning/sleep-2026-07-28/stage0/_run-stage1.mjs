/**
 * Crucible Stage 1 launcher — Anchor sleep cycle 2026-07-28 (v1.2).
 * FULL depth, seats from Anchor model prefs (coding=claude, review=grok).
 * Output: planning/sleep-2026-07-28/stage1/
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const CRUCIBLE_BIN = 'C:\\dev\\trio\\crucible\\bin';
const { buildLiveCrucibleAgent } = await import(pathToFileURL(path.join(CRUCIBLE_BIN, 'enhanced.mjs')).href);
const { runStage1 } = await import(pathToFileURL(path.join(CRUCIBLE_BIN, 'stage1.mjs')).href);

const OUT = 'C:/dev/Anchor/planning/sleep-2026-07-28/stage1';
mkdirSync(OUT, { recursive: true });
mkdirSync(OUT + '/artifacts', { recursive: true });

// Explicit seating (prefs: coding=claude, review=grok)
process.env.CODING_FAMILY = process.env.CODING_FAMILY || 'claude';
process.env.REVIEW_FAMILY = process.env.REVIEW_FAMILY || 'grok';
process.env.CROSS_MODEL = process.env.CROSS_MODEL || 'true';
process.env.TRIO_TIER = process.env.TRIO_TIER || 'standard';
process.env.TRIO_DRIVER = process.env.TRIO_DRIVER || 'claude';
process.env.TRIO_DRIVER_REVIEW = process.env.TRIO_DRIVER_REVIEW || 'grok-cli';
process.env.CRUCIBLE_AGENT_LIVE = '1';
// Do not force API key path for Claude subscription seats
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
  'Dead controls eliminated for Retry (session attach), Diagnose (Doctor), and a single restart control — work or not shown.',
  'Attach path honesty: timeout classified as timeout (not unknown-session); error UI does not double-print; Retry re-issues a viable action or explains why not.',
  'Usage/time/cost surfacing: dashboard, workbench tiles, and session chrome render existing rollups; cost_usd==0 renders as (subscription) with reason, never $0.00; unmeasured engines show labelled unmeasured, never blank or fake zero.',
  'Doctor actually doctors: Diagnose runs a real diagnosis (not shell/seed/plan-only theater); banner→Doctor handoff carries issue payload; Claude/Gemini/Grok each report independently.',
  'Stop/summary/restart: stopping leaves a tile summarizing in-flight work; one restart control; restart quality is documented and testable.',
  'File preview: shared preview path shows human-friendly Word/PPTX/Excel/PDF (reuse working new-window path); binary no longer dumps as text.',
  'Projects default collapsed: folders open collapsed by default; user preference remembered; root cause is real JS/CSS path.',
  'Cadence is real: status cadence owned by Anchor from live telemetry on a timer, not prose that looks like a scheduler.',
  'Gates: surface-bearing waves have failure-state tables with unknown and empty as separate rows; scoped pytest gate-command per wave with -v; UI waves assert on rendered HTML + node --check; delta-coverage for new routes/handlers/frontend.',
  'Handoff hygiene: doc-trio + foreman.config.json only under planning/sleep-2026-07-28/stage2/; Foreman cwd that directory; root foreign artifacts untouched; commits land per wave; EXECUTION-LOG appended; attestation count reported.',
];

const contextBundle = {
  intake: 'C:/dev/Anchor/planning/sleep-2026-07-28/SLEEP-BRIEF.md',
  stage0: 'C:/dev/Anchor/planning/sleep-2026-07-28/stage0/STAGE0-FRAMING.md',
  lock: 'C:/dev/Anchor/planning/sleep-2026-07-28/stage0/STAGE0-LOCKED.json',
  repo: 'C:/dev/Anchor',
  branch: 'v1.2',
  build_scope: ['S2', 'S4', 'S3', 'S5', 'S6', 'S7', 'S8'],
  post_build: ['S1'],
  emit_only: 'planning/sleep-2026-07-28/stage2/',
  constraints: [
    'Never silent zero; unknown ≠ empty ≠ zero',
    'No pricing table; cost=(subscription) when unmeasured',
    'Dead control ≡ crash severity',
    'v1.2 only; v1.1.x steward-free',
    'Scoped pytest -v gates only (money history)',
    'UI: generate_html render + node --check (see tests/test_auth_reprompt_2026_07_28.py)',
    'Hardening gate 0080/0081 will fire — failure-state tables required',
    'Delta-coverage 0091 — tests/test_<subject>_<date>.py naming routes/handlers/UI',
  ],
  premise_corrections: [
    'S4: rollup data exists; failure is surfacing only; cost 0.0 must not show as $0.00',
    'S7: no details open in markup; expansion is JS/CSS',
  ],
};

writeFileSync(OUT + '/_stage1-context.json', JSON.stringify({ northStar, criteria, contextBundle }, null, 2) + '\n', 'utf8');

console.log('[sleep-stage1] building live agent from coding/review family prefs...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[sleep-stage1] agent built; routes=', JSON.stringify(routes));
console.log('[sleep-stage1] starting runStage1 (FULL depth)...');

try {
  const result = await runStage1({
    agent,
    northStar,
    criteria,
    depth: 'FULL',
    artifactsDir: OUT + '/artifacts',
    statusLog: OUT + '/_crucible-status.log',
    routes,
    // Give Sharks the sleep brief path via log/context if supported
    log: (m) => console.log(`[stage1] ${m}`),
  });
  writeFileSync(OUT + '/stage1-result.json', JSON.stringify(result, null, 2), 'utf8');
  const plan = result.plan || {};
  const loop = result.loop || {};
  const md = [
    '# Master Plan (DRAFT) — Anchor sleep cycle 2026-07-28',
    '',
    '_Crucible Stage 1 · FULL · seats from Anchor prefs (coding=claude, review=grok). Draft for user approval._',
    '',
    '## North Star (locked Stage 0)',
    '',
    northStar,
    '',
    '## Success criteria',
    '',
    ...criteria.map((c, i) => `${i + 1}. ${c}`),
    '',
    '## Convergence',
    `- converged: ${JSON.stringify(loop.converged ?? loop.status ?? 'see stage1-result.json')}`,
    `- rounds: ${JSON.stringify(loop.rounds ?? loop.round ?? 'n/a')}`,
    `- open findings: ${JSON.stringify((loop.openFindings || loop.findings || []).length ?? 'n/a')}`,
    `- families reached: ${JSON.stringify([...(tracker.families ? tracker.families() : [])])}`,
    '',
    '## Phased plan',
    '```json',
    JSON.stringify(plan, null, 2),
    '```',
    '',
    '## Scope stamp',
    '- Build: S2, S4, S3, S5, S6, S7, S8',
    '- Post-build validation (not Foreman): S1',
    '- Emit: planning/sleep-2026-07-28/stage2/ only',
  ].join('\n');
  writeFileSync(OUT + '/MASTER-PLAN-DRAFT.md', md, 'utf8');
  console.log('[sleep-stage1] DONE — wrote MASTER-PLAN-DRAFT.md + stage1-result.json');
  process.exit(0);
} catch (e) {
  writeFileSync(OUT + '/stage1-ERROR.txt', String(e && e.stack || e), 'utf8');
  console.log('[sleep-stage1] HALT/ERROR:', e && e.message);
  console.log('[sleep-stage1] (round-cap HALT is normal — best draft in artifacts/)');
  process.exit(e && e.name === 'HaltError' ? 2 : 1);
}

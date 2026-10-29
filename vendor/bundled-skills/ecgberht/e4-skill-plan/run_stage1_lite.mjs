/**
 * Ecgberht E4 — Crucible Stage 1 LITE for Foundry skill+engine.
 * Seats: Anchor model prefs via buildLiveCrucibleAgent (no hardcoded families).
 * Target tree: <path> only — never Anchor-release-v1.0.
 */
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { buildLiveCrucibleAgent } from 'fil<path>';
import { runStage1 } from 'fil<path>';

const ROOT = '<path>';
const OUT = `${ROOT}/stage1`;
const ART = `${OUT}/artifacts`;
for (const d of [OUT, ART]) {
  try { mkdirSync(d, { recursive: true }); } catch {}
}

const northStar = readFileSync(`${ROOT}/NORTH-STAR.md`, 'utf8');
const criteria = [
  'Installable Foundry skill ecgberht with SKILL.md + templates + schema',
  'Closed engine verb list with write-authority tests (Face vs Strip)',
  'Face+Strip protocol; portfolio strip-first ranking; heal law',
  'Dispatch table for depth; human override with receipt',
  'Compose trio/foundry only — no harness / no OpenClaw / no v1.0 release edits',
  'Subscription seating via Anchor prefs; honest cross_model stamp',
];

console.log('[e4-stage1-lite] trio pin note: <path> @ see git rev-parse');
console.log('[e4-stage1-lite] building live agent from Anchor prefs...');
const { agent, tracker, routes, families, drafterFamily } = await buildLiveCrucibleAgent({
  target: '<path>',
  log: (m) => console.log('[agent]', m),
});
console.log('[e4-stage1-lite] families=', JSON.stringify(families), 'drafter=', drafterFamily);
console.log('[e4-stage1-lite] routes=', JSON.stringify(routes));
console.log('[e4-stage1-lite] starting runStage1 depth=LITE...');

try {
  const result = await runStage1({
    agent,
    northStar,
    criteria,
    depth: 'LITE',
    artifactsDir: ART,
    statusLog: `${OUT}/_crucible-status.log`,
    routes,
    log: (m) => console.log('[stage1]', m),
  });
  writeFileSync(`${OUT}/stage1-result.json`, JSON.stringify(result, null, 2));
  const plan = result.plan || result.masterPlan || {};
  const loop = result.loop || {};
  const fams = tracker.families ? [...tracker.families()] : [];
  const md = [
    '# Master Plan (DRAFT) — Ecgberht Foundry skill + engine',
    '',
    '_Crucible Stage 1 · depth **LITE** · for John approval (SHOW-THE-ARTIFACT)._',
    '',
    '## Substrate stamp',
    `- families: ${JSON.stringify(families)}`,
    `- cross_model: ${families?.cross_model === true}`,
    `- drafter: ${drafterFamily}`,
    `- reached families: ${JSON.stringify(fams)}`,
    '',
    '## Convergence',
    `- status: ${JSON.stringify(loop.converged ?? loop.status ?? 'see stage1-result.json')}`,
    '',
    '## Phased plan (machine output)',
    '```json',
    JSON.stringify(plan, null, 2),
    '```',
    '',
    '## Next',
    'On approval → Stage 2 LITE → Foreman standard.',
  ].join('\n');
  writeFileSync(`${OUT}/MASTER-PLAN-DRAFT.md`, md);
  try {
    const best = `${ART}/BEST-DRAFT.md`;
    const { copyFileSync, existsSync } = await import('node:fs');
    if (existsSync(best)) copyFileSync(best, `${OUT}/BEST-DRAFT.md`);
  } catch {}
  console.log('[e4-stage1-lite] DONE — MASTER-PLAN-DRAFT.md + stage1-result.json');
  console.log('[e4-stage1-lite] HALT for human: master-plan-approval');
} catch (e) {
  writeFileSync(`${OUT}/stage1-ERROR.txt`, String(e && e.stack || e));
  console.log('[e4-stage1-lite] HALT/ERROR:', e && e.message);
  process.exitCode = e?.exitCode === 3 || /HALT/i.test(String(e && e.message)) ? 0 : 1;
}

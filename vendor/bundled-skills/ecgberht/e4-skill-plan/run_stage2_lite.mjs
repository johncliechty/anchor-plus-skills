/**
 * Ecgberht E4 — Crucible Stage 2 LITE after Master Plan lock (+ discovery A1).
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync, copyFileSync } from 'node:fs';
import { buildLiveCrucibleAgent } from 'file:///C:/dev/trio/crucible/bin/enhanced.mjs';
import { runStage2 } from 'file:///C:/dev/trio/crucible/bin/stage2.mjs';

const ROOT = 'C:/dev/Ecgberht/e4-skill-plan';
const OUT = `${ROOT}/stage2`;
const ART = `${OUT}/artifacts`;
for (const d of [OUT, ART]) {
  try { mkdirSync(d, { recursive: true }); } catch {}
}

const northStar = readFileSync(`${ROOT}/NORTH-STAR.md`, 'utf8');
const masterPlan = [
  readFileSync(`${ROOT}/MASTER-PLAN-LOCKED.md`, 'utf8'),
  '',
  '---',
  '',
  readFileSync(`${ROOT}/MASTER-PLAN-DRAFT.md`, 'utf8'),
].join('\n');

console.log('[e4-stage2-lite] building live agent from Anchor prefs...');
const { agent, tracker, routes, families, drafterFamily } = await buildLiveCrucibleAgent({
  target: 'C:/dev/Ecgberht',
  log: (m) => console.log('[agent]', m),
});
console.log('[e4-stage2-lite] families=', JSON.stringify(families), 'drafter=', drafterFamily);

try {
  const result = await runStage2({
    agent,
    northStar,
    masterPlan,
    depth: 'LITE',
    outputDir: OUT,
    artifactsDir: ART,
    statusLog: `${OUT}/_crucible-status.log`,
    routes,
    log: (m) => console.log('[stage2]', m),
  });
  writeFileSync(`${OUT}/stage2-result.json`, JSON.stringify(result, null, 2));
  console.log('[e4-stage2-lite] DONE — stage2-result.json');
  console.log('[e4-stage2-lite] HALT for human: implementation-plan approval');
} catch (e) {
  writeFileSync(`${OUT}/stage2-ERROR.txt`, String(e && e.stack || e));
  console.log('[e4-stage2-lite] HALT/ERROR:', e && e.message);
  // Cap drafts often land under _unapproved-cap-draft
  try {
    if (existsSync(`${OUT}/_unapproved-cap-draft`)) {
      console.log('[e4-stage2-lite] unapproved cap draft present under stage2/_unapproved-cap-draft');
    }
  } catch {}
  process.exitCode = e?.exitCode === 3 || /HALT/i.test(String(e && e.message)) ? 0 : 1;
}

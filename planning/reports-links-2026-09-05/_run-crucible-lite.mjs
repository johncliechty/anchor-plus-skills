/**
 * Crucible LITE — Anchor: every report is a link (plan outline + register); a runnable deliverable
 * opens in an Anchor window (John, 2026-09-05). THE FIRST RUN WITH THE ELEGANCE PASS INSIDE
 * (stage1 after the plan, stage2 after the decomposition; CUT blocks). Seats from the dashboard.
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { buildLiveCrucibleAgent } from 'file:///C:/dev/trio/crucible/bin/enhanced.mjs';
import { runStage1 } from 'file:///C:/dev/trio/crucible/bin/stage1.mjs';
import { runStage2 } from 'file:///C:/dev/trio/crucible/bin/stage2.mjs';

const ROOT = 'C:/dev/Anchor/planning/reports-links-2026-09-05';
const TARGET = 'C:/dev/Anchor';
const S1 = `${ROOT}/stage1`;
const S2 = `${ROOT}/stage2`;
const HANDOFF = `${ROOT}/handoff`;
for (const d of [S1, `${S1}/artifacts`, S2, `${S2}/artifacts`, HANDOFF]) {
  try { mkdirSync(d, { recursive: true }); } catch {}
}
const say = (tag) => (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] [${tag}] ${m}`);

const northStar = readFileSync(`${ROOT}/NORTH-STAR.md`, 'utf8');
const research = readFileSync(`${ROOT}/baseline-context.md`, 'utf8');
const TEST_COMMAND = 'python -m pytest tests/test_steward_deliverables.py tests/test_status_lookthrough_2026_09_04.py tests/test_cockpit_status_window_2026_09_03.py tests/test_reports_links_2026_09_05.py -q -p no:cacheprovider';
const criteria = [
  'A finished run registers itself: when a Gandalf run finalizes, a researchPrime / lane job finishes, or a Foreman wave GOes, one row is appended (idempotent on what+where) to the effort\'s DELIVERABLES.md (the project root when the run has no effort): what, an Anchor route the cockpit can open, the date, and the active roadmap step',
  'A register row may point at an Anchor route: a Where cell that is /report/… or /artifact/… (Anchor\'s own contained routes) is openable and renders as a link opening in a new window, in the deliverables tile AND under its step in the plan outline; rows outside the effort and outside those routes still render as text',
  'A runnable deliverable has a Run link: a register row declaring run: <command> renders a Run link that opens a cockpit terminal (general lane) in the project\'s tree with the command staged as a pending paste (Enter runs it) — token-gated, never auto-submitted; documents keep their open link',
  'Nothing regresses and it is seen: the steward/cockpit nets stay green; a Gandalf run on a real project is opened from the plan outline AND the deliverables tile on the page, and a run: row opens a terminal with the command staged (Playwright screenshots) before v1.2.13 ships',
];
const acceptanceCriteria = [
  `done-when: ${TEST_COMMAND} is green (wave 1 creates tests/test_reports_links_2026_09_05.py): a Gandalf finalize on a temp project appends a register row with a /artifact route and the active step; read_deliverables marks a /report row openable with kind url; a run: row carries its command; the two renderings read the same rows`,
];
// PROVENANCE for the elegance pass: John's words are user-ratified; the criteria above are the planner's.
const provenance = {
  userRatified: [
    'John 2026-09-05: "when reports are built (e.g. a Gandalf report, or a researchPrime plan or report) they need to show up with a clickable link in the plan outline (so I can open up the details and click) as well as they always need to have a clickable link in the deliverable section"',
    'John 2026-09-05: "If it is a bit of code that opens in another window and runs locally on puter, but displays in an anchor window that still needs a clickable link"',
    'John 2026-09-04 (law 14): a plan forward lives as a clickable row in DELIVERABLES.md and a bullet summary in the dialogue',
  ],
  records: [
    'campaign journal 0010: "a step producing a human-facing artifact is not done until listed" (the register convention)',
    'planning/deliverable-runner-2026-09-04/NOTE.md (design note; John: "did you get that included in Anchor?" — no)',
    'the containment rule: read_deliverables opens only in-effort files (2026-08-25)',
  ],
  proposerWritten: criteria.map((c) => 'criterion: ' + c.slice(0, 160)),
};

say('launch')(`Crucible LITE on ${TARGET} (elegance pass inside)`);
const { agent, routes, families, drafterFamily } = await buildLiveCrucibleAgent({ target: TARGET, log: say('agent') });
say('launch')(`families=${JSON.stringify(families)} drafter=${drafterFamily}`);
say('launch')(`routes=${JSON.stringify(routes)}`);
writeFileSync(`${ROOT}/_seats.json`, JSON.stringify({ families, drafterFamily, routes }, null, 2));

let masterPlan = null;
try {
  const r1 = await runStage1({
    agent, northStar, criteria, research, acceptanceCriteria, provenance, depth: 'LITE', approved: true,
    grasscatcherPath: `${ROOT}/GRASSCATCHER.md`, artifactsDir: `${S1}/artifacts`,
    statusLog: `${ROOT}/_crucible-status.log`, routes, log: say('stage1'),
  });
  writeFileSync(`${S1}/stage1-result.json`, JSON.stringify(r1, null, 2));
  const best = `${S1}/artifacts/BEST-DRAFT.md`;
  const approvedPlan = r1?.approval?.masterPlan;
  const planText = typeof approvedPlan === 'string' ? approvedPlan : (approvedPlan ? JSON.stringify(approvedPlan, null, 2) : null);
  const bestText = existsSync(best) ? readFileSync(best, 'utf8') : '';
  masterPlan = [planText || JSON.stringify(r1?.plan || {}, null, 2), bestText ? '\n---\n' + bestText : ''].join('\n');
  writeFileSync(`${S1}/MASTER-PLAN.md`, masterPlan);
  say('stage1')(`DONE — master plan ${masterPlan.length} chars; elegance cuts=${JSON.stringify(r1?.elegance?.cuts || [])}`);
} catch (e) {
  writeFileSync(`${S1}/stage1-ERROR.txt`, String((e && e.stack) || e));
  say('stage1')(`HALT/ERROR: ${e && e.message}`);
  const best = `${S1}/artifacts/BEST-DRAFT.md`;
  if (!existsSync(best)) { process.exitCode = 1; process.exit(); }
  say('stage1')('continuing to Stage 2 on the persisted BEST-DRAFT (the steward\'s call, stamped)');
  masterPlan = readFileSync(best, 'utf8');
  writeFileSync(`${S1}/MASTER-PLAN.md`, '<!-- from BEST-DRAFT after a Stage-1 HALT -->\n' + masterPlan);
}

try {
  const r2 = await runStage2({
    agent, northStar, masterPlan, criteria, acceptanceCriteria, research, provenance,
    title: 'Anchor: every report is a link; a runnable deliverable opens in an Anchor window',
    summary: 'Finished runs register themselves in DELIVERABLES.md with an Anchor route and their roadmap step; route-valued rows are openable in the tile and under their step in the plan outline; a run: row gets a Run link that stages the command in a cockpit terminal (Enter runs it); seen on the page before v1.2.13.',
    testCommand: TEST_COMMAND, depth: 'LITE', approved: true,
    outputDir: HANDOFF, artifactsDir: `${S2}/artifacts`,
    statusLog: `${ROOT}/_crucible-status-stage2.log`, routes, log: say('stage2'),
  });
  writeFileSync(`${S2}/stage2-result.json`, JSON.stringify(r2, null, 2));
  say('stage2')('DONE — doc-trio emitted to handoff/');
} catch (e) {
  writeFileSync(`${S2}/stage2-ERROR.txt`, String((e && e.stack) || e));
  say('stage2')(`HALT/ERROR: ${e && e.message}`);
  process.exitCode = /HALT/i.test(String(e && e.message)) ? 0 : 1;
}
say('launch')('END');

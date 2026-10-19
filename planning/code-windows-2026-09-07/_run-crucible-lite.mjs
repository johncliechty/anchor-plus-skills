/**
 * Crucible LITE — Anchor: code opens where it runs (John, 2026-09-07): notebooks in the project's own
 * JupyterLab, short code as a notebook, long code in the editor, live links from the register.
 * Elegance pass + RC-8 inside (stage 1 after the plan, stage 2 after the decomposition). Seats from the
 * dashboard (review family = Grok).
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { buildLiveCrucibleAgent } from 'file:///C:/dev/trio/crucible/bin/enhanced.mjs';
import { runStage1 } from 'file:///C:/dev/trio/crucible/bin/stage1.mjs';
import { runStage2 } from 'file:///C:/dev/trio/crucible/bin/stage2.mjs';

const ROOT = 'C:/dev/Anchor/planning/code-windows-2026-09-07';
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
// no -q: the builder reads pytest's counts (crucible journal 0096)
const TEST_COMMAND = 'python -m pytest tests/test_code_windows_2026_09_07.py tests/test_steward_deliverables.py tests/test_reports_links_2026_09_05.py -p no:cacheprovider';
const criteria = [
  'A project\'s own JupyterLab is managed like a preview: started on demand (cwd = the project folder) on an OS-assigned free port that is never 8777, with its own token, registered, listed, stoppable, reaped when dead (the preview_server discipline)',
  'A .ipynb row (register, plan outline, files tile) opens in a new window at the lab\'s /lab/tree/<rel> for that file, starting or restarting the lab if needed — never a blank page',
  'A .py or .R row that is short (<= 120 lines) or marked as a notebook (# %% cells or "# notebook" in its first lines) is converted ONCE to a sibling one-cell .ipynb (nbformat 4 JSON written with stdlib; kernel python3 or ir) and opened in JupyterLab; longer code opens in the local editor (code -r <file>); the row says which (notebook / editor); an existing .ipynb is never overwritten',
  'A Where cell that is a http://localhost:<port>/…, http://127.0.0.1:<port>/… or http://<this machine\'s tailnet name>/… URL renders as a link opening in a new window; every other host stays text',
  'Seen on the page before it ships: on a real project a .ipynb row opens the lab with the file selected, a short .py opens as a notebook, a long .py opens in the editor, a live-link row opens (Playwright screenshots); nets green; then the release pipeline',
];
const acceptanceCriteria = [
  `done-when: ${TEST_COMMAND} is green (wave 1 extends tests/test_code_windows_2026_09_07.py): a stubbed lab start records a non-8777 port + token and is listed/stopped/reaped; a .ipynb row resolves to /lab/tree/<rel>?token=; a short .py converts once to a sibling .ipynb with the right kernel and never overwrites; a long .py resolves to the editor; localhost/127.0.0.1/tailnet Where cells are openable links and other hosts are text`,
];
const provenance = {
  userRatified: [
    'John 2026-09-07: "the jupyter notebooks need to come up everytime python or R code is called (at least if the code is descriptive/shorter) longer bits of code can have a GUI that runs in a window ... a bit like running in something like VS Code"',
    'John 2026-09-05: "If it is a bit of code that opens in another window and runs locally on puter, but displays in an anchor window that still needs a clickable link"',
    'John 2026-09-06: "The clickable links need to be in the plan, in the deliverables and in the files."',
  ],
  records: [
    'Ecgberht journal 0110 (2026-09-07): a JupyterLab/Shiny address is unreachable from the register and the plan; the steward wrote a launch page to work around it',
    'preview_server.py: managed local servers on a free port never 8777, registered, reaped (the discipline to reuse)',
    'planning/deliverable-runner-2026-09-04/NOTE.md: the app slot / remote display are parked non-goals',
  ],
  proposerWritten: criteria.map((c) => 'criterion: ' + c.slice(0, 160)),
};

say('launch')(`Crucible LITE on ${TARGET} (elegance pass + RC-8 inside)`);
const { agent, routes, families, drafterFamily } = await buildLiveCrucibleAgent({ target: TARGET, log: say('agent') });
say('launch')(`families=${JSON.stringify(families)} drafter=${drafterFamily}`);
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
    title: 'Anchor: code opens where it runs — notebooks in the project\'s JupyterLab, short code as a notebook, long code in the editor, live links from the register',
    summary: 'A per-project JupyterLab managed like a preview; .ipynb rows open in it; short .py/.R rows convert once to a notebook and open there, long ones open in VS Code; localhost/tailnet URLs in the register are links; seen on the page before shipping.',
    testCommand: TEST_COMMAND, depth: 'LITE', approved: true,
    outputDir: HANDOFF, artifactsDir: `${S2}/artifacts`,
    statusLog: `${ROOT}/_crucible-status-stage2.log`, routes, log: say('stage2'),
  });
  writeFileSync(`${S2}/stage2-result.json`, JSON.stringify(r2, null, 2));
  say('stage2')('DONE — doc-trio emitted to handoff/');
} catch (e) {
  writeFileSync(`${S2}/stage2-ERROR.txt`, String((e && e.stack) || e));
  say('stage2')(`HALT/ERROR: ${e && e.message}`);
  process.exitCode = /human-lockable/i.test(String(e && e.message)) ? 0 : 1;
}
say('launch')('END');

/**
 * Crucible LITE — Anchor: ChatGPT is a first-class Terminal engine (John, 2026-09-05).
 * Seats from the Anchor dashboard via buildLiveCrucibleAgent. Stage 1 → Stage 2 in one process.
 * The gates: the steward's call (John asked "do the plan, integrate"); John can object.
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { buildLiveCrucibleAgent } from 'file:///C:/dev/trio/crucible/bin/enhanced.mjs';
import { runStage1 } from 'file:///C:/dev/trio/crucible/bin/stage1.mjs';
import { runStage2 } from 'file:///C:/dev/trio/crucible/bin/stage2.mjs';

const ROOT = 'C:/dev/Anchor/planning/chatgpt-terminal-2026-09-05';
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
const TEST_COMMAND = 'python -m pytest tests/test_backend_chatgpt.py tests/test_anchor_settings.py tests/test_chatgpt_lane_routing.py tests/test_chatgpt_terminal_2026_09_05.py tests/test_model_switch_w7.py -q -p no:cacheprovider';
const criteria = [
  'A terminal opens on ChatGPT: with default_cli=chatgpt or the engine toggle, POST /api/rnd/term_start starts a PTY running the Codex TUI in the session worktree (--cd <worktree>, --no-alt-screen, -s workspace-write; approvals left to the user), the lane seed is written exactly once and the greet arrives, the registry record carries backend chatgpt, and term_set_engine switches a live session to and from chatgpt in the same worktree with no orphan PTY',
  'The truth tables agree: the Terminal picker shows "ChatGPT — ready" (no "bridge pending" anywhere: capability matrix, option labels, capability note, anchor_settings comments); VALID_DEFAULT_CLIS includes chatgpt and save_settings(default_cli="chatgpt") persists; _check_engine_allowed no longer gates chatgpt; a host without the Codex binary still fails closed with the existing chatgpt-terminal-binary-missing error',
  'Doctor posture and honest accounting: live_doctor_session(backend="chatgpt") launches with -s read-only (a DOCTOR_READONLY_CLI_ARGS entry); no session-id pin exists for Codex so the usage state is uncorrelated and a rollup that includes it is stamped partial (chatgpt segment unmeasured) — never an mtime guess, never a fabricated $0.00',
  'Nothing regresses and it is seen: the terminal nets stay green under the stub PTY (ANCHOR_PTY_BACKEND=stub + ANCHOR_ENGINE_CMD), _LIVE_ENGINE_BASENAMES still refuses a real codex spawn under test, the 5 AM v3/v4 walks are unchanged, distro.py import scan stays clean; every test that pinned "bridge pending" is rewritten to the new truth in the same wave; a ChatGPT terminal opened from the dashboard shows its greet on the page (Playwright) before v1.2.12 ships',
];
const acceptanceCriteria = [
  `done-when: ${TEST_COMMAND} is green (wave 1 creates tests/test_chatgpt_terminal_2026_09_05.py), a stub-PTY start_session(backend="chatgpt") records backend chatgpt with the seed written once and argv carrying --no-alt-screen and -s workspace-write, switch_engine to/from chatgpt leaves no orphan PTY, and the capability matrix reports terminal chatgpt status ready / selectable true`,
];

say('launch')(`Crucible LITE on ${TARGET}`);
const { agent, tracker, routes, families, drafterFamily } = await buildLiveCrucibleAgent({ target: TARGET, log: say('agent') });
say('launch')(`families=${JSON.stringify(families)} drafter=${drafterFamily}`);
say('launch')(`routes=${JSON.stringify(routes)}`);
writeFileSync(`${ROOT}/_seats.json`, JSON.stringify({ families, drafterFamily, routes }, null, 2));

let masterPlan = null;
try {
  const r1 = await runStage1({
    agent, northStar, criteria, research, acceptanceCriteria, depth: 'LITE', approved: true,
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
  say('stage1')(`DONE — master plan ${masterPlan.length} chars`);
} catch (e) {
  writeFileSync(`${S1}/stage1-ERROR.txt`, String((e && e.stack) || e));
  say('stage1')(`HALT/ERROR: ${e && e.message}`);
  const best = `${S1}/artifacts/BEST-DRAFT.md`;
  if (!existsSync(best)) { process.exitCode = 1; process.exit(); }
  say('stage1')('continuing to Stage 2 on the persisted BEST-DRAFT (human-lockable/cap draft — the steward\'s call, stamped)');
  masterPlan = readFileSync(best, 'utf8');
  writeFileSync(`${S1}/MASTER-PLAN.md`, '<!-- from BEST-DRAFT after a Stage-1 HALT -->\n' + masterPlan);
}

try {
  const r2 = await runStage2({
    agent, northStar, masterPlan, criteria, acceptanceCriteria, research,
    title: 'Anchor: ChatGPT is a first-class Terminal engine',
    summary: 'Open the last dashboard role to ChatGPT: the Codex TUI in the cockpit terminal (seeded once, engine-switchable, Doctor read-only posture), truth tables and settings agree, usage honestly unmeasured (Option C), every "bridge pending" pin rewritten, seen on the page before v1.2.12 ships.',
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

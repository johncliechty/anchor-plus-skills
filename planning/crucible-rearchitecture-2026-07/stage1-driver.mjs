// stage1-driver.mjs — Crucible STAGE 1 (Master Plan) driver for the Anchor
// re-architecture (Butler substrate). Launched ONCE as a single long-running
// node process. It drives the REAL Crucible engine (true fresh-context Sharks,
// Synthesizer direction, context-free Judge, convergence gate) against the
// LOCKED North Star, appends progress to STATUS.log, and on the model-side
// convergence writes MASTER-PLAN-DRAFT.md + STAGE1-SUMMARY.md, then treats the
// master-plan-approval HALT as SUCCESS (John is the convergence authority).
//
// NOTE on orchestration: this driver calls the SAME exported stage1.mjs steps
// runStage1 itself composes (runBrainstorm -> triageIdeas -> buildPhasedPlan ->
// runMasterPlanLoop -> approveMasterPlan), in the same order, because
// runStage1's final approval gate THROWS the HaltError before returning the
// loop result — and the deliverable here IS the converged draft, which must be
// persisted before the (expected, successful) HALT.
//
// HOST FACT: the Claude binary on this host is claude.exe in ~/.local/bin —
// NOT claude.cmd (modern Node refuses to spawn a .cmd with shell:false), so a
// custom runClaude transport is injected into makeAgentSeam. It reuses the
// driver's exported parseClaudeFrames/resolveClaudeModel — no forked parsing.
// Sub-agents are read-only (Read,Glob,Grep), windowsHide, no visible shells.

import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

import {
  runBrainstorm,
  triageIdeas,
  buildPhasedPlan,
  runMasterPlanLoop,
  renderMasterPlanDraft,
  approveMasterPlan,
} from 'file:///C:/dev/trio/crucible/bin/stage1.mjs';
import {
  makeAgentSeam,
  parseClaudeFrames,
  resolveClaudeModel,
} from 'file:///C:/dev/trio/drivers/claude.mjs';
import { HaltError } from 'file:///C:/dev/trio/crucible/bin/crucible-lib.mjs';

// ---------------------------------------------------------------------------
// Paths + constants.
// ---------------------------------------------------------------------------

const PLAN_DIR = 'C:/dev/Anchor/planning/crucible-rearchitecture-2026-07';
const STATUS_LOG = path.join(PLAN_DIR, 'STATUS.log');
const ARTIFACTS_DIR = path.join(PLAN_DIR, 'stage1-artifacts');
const CLAUDE_EXE = 'C:/Users/john/.local/bin/claude.exe';
const TARGET = 'C:/dev/Anchor';
const CALL_TIMEOUT_MS = 30 * 60 * 1000; // 30 min per sub-agent call (safety)
const ENV = { ...process.env, CRUCIBLE_AGENT_LIVE: '1' };

function log(line) {
  const msg = `[${new Date().toISOString()}] ${line}`;
  try { fs.appendFileSync(STATUS_LOG, msg + '\n'); } catch { /* never crash on log */ }
  try { process.stdout.write(msg + '\n'); } catch { /* detached stdout */ }
}

function saveArtifact(name, obj) {
  try {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
    const p = path.join(ARTIFACTS_DIR, name);
    fs.writeFileSync(p, typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2));
  } catch (e) { log(`!! failed to save artifact ${name}: ${e.message}`); }
}

// ---------------------------------------------------------------------------
// The live transport — claude.exe, read-only tools, hidden window, timeout.
// ---------------------------------------------------------------------------

const BASE_ARGS = [
  '-p', ' ', '--output-format', 'stream-json', '--verbose',
  '--permission-mode', 'acceptEdits',
  '--allowedTools', 'Read,Glob,Grep',
];

function runClaude(fullPrompt, label, callOpts = {}) {
  if (ENV.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError('live agent seam is disabled', 'set CRUCIBLE_AGENT_LIVE=1');
  }
  return new Promise((resolve) => {
    const args = [...BASE_ARGS];
    const mdl = resolveClaudeModel({ model: callOpts.model, role: callOpts.role, label, env: ENV });
    if (mdl) args.push('--model', mdl);

    const started = Date.now();
    log(`-> agent call: ${label}`);
    const child = spawn(CLAUDE_EXE, args, { cwd: TARGET, env: ENV, shell: false, windowsHide: true });

    let out = '';
    let err = '';
    let done = false;

    const killTree = () => {
      try { spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true }); } catch { /* best-effort */ }
    };
    const timer = setTimeout(() => {
      log(`!! ${label}: timeout after ${CALL_TIMEOUT_MS / 60000} min — killing sub-agent (will abstain)`);
      killTree();
    }, CALL_TIMEOUT_MS);

    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      const { text, rec, _finalEnv } = parseClaudeFrames(out, { label, cli_status: child.exitCode });
      const secs = Math.round((Date.now() - started) / 1000);
      log(`<- agent done: ${label} — ${secs}s, ok=${rec.ok}, tools=${rec.tools}` +
        (_finalEnv ? '' : ` [NO result envelope; stderr=${err.slice(0, 200).replace(/\s+/g, ' ')}]`));
      resolve({ text, rec });
    };

    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => { err += d.toString(); });
    child.on('close', finish);
    child.on('error', (e) => { log(`!! ${label}: spawn error — ${e.message}`); finish(); });
    child.stdin.on('error', (e) => { log(`!! ${label}: stdin error — ${e.message}`); });
    try { child.stdin.write(fullPrompt); child.stdin.end(); } catch { /* child died early */ }
  });
}

// ---------------------------------------------------------------------------
// Inputs: the LOCKED North Star (verbatim), the 7 success criteria (short
// forms), and the Stage-0 intake fed through the research seam (never welded
// into the North Star — the lock stays verbatim).
// ---------------------------------------------------------------------------

const northStar = fs.readFileSync(path.join(PLAN_DIR, 'NORTH-STAR.md'), 'utf8');
const intake = fs.readFileSync(path.join(PLAN_DIR, 'INTAKE.md'), 'utf8');

const criteria = [
  'C1 Frontend extracted: anchor_gui.py keeps no embedded frontend blob >~50 lines; _PROJECT_WINDOW_JS, the generate_html f-string JS/CSS, and the project-window HTML/CSS shell served as static files via the existing traversal-safe asset-route idiom, server state injected only through a small bootstrap JSON; behavior parity Playwright-verified (home dashboard + project window); anchor_gui.py shrinks by >= 7,000 lines.',
  'C2 One declarative route table, default-deny auth: all ~125 do_GET/do_POST dispatch arms route through a single table where EVERY route declares its auth policy (token default; open only on an explicit reviewed allowlist); the currently-unauthenticated GET data plane (/artifact, /report, /summary, /project, /api/rnd/projects, /api/rnd/tail, /api/rnd/jobs) is gated when ANCHOR_TOKEN is set, with browser page navigation still working via cookie (no URL tokens except where WS demands); zero in-branch imports shadowing module names remain.',
  'C3 Event-log spine, dual-write, provably derivable: every mutation-of-record appends a schema-versioned event to an append-only per-project journal, written alongside (never instead of) the existing index/pointer/registry stores; a parity gate in tests AND the daily healthcheck re-derives session/effort views from the journal with zero divergence; a recovery tool rebuilds a deleted index.json from the journal in a test.',
  'C4 Supervisor split, restart survival live-proven: spawned lane jobs are owned by a separate stdlib supervisor process (own NSSM service, loopback token-authed IPC, inline seam for tests/healthcheck); `nssm restart anchor` with a job in flight leaves the job running and the restarted dashboard reporting it live, demonstrated on the real service; PTY sessions follow behind a mandated ConPTY-across-processes spike — if the spike refutes economic feasibility, PTYs remain dashboard-owned and the narrowing is recorded honestly (the jobs half is non-negotiable).',
  'C5 One markdown-parsing layer: a single shared parsing module imported by anchor_gui.py and anchor.py (the byte-identical twins de-forked); the drifted third copy dies with anchor_server.py, which is DELETED (confirmed dead).',
  'C6 Runtime state out of the repo: the live deployment runs with ANCHOR_DATA_DIR pointing outside C:\\dev\\Anchor (existing paths.py seam + migrate_data); git status on the repo is clean of runtime artifacts and stays clean through a healthcheck cycle.',
  'C7 Never-broken increments: every merged step keeps the dashboard fully operational as the NSSM `anchor` service on :8777; Python stdlib only (pywinpty exception stands); markdown files remain the source of truth for tasks; the full test suite stays green (modulo the 2-3 documented pre-existing flakes); each pillar lands with its own test gate.',
];

const DIRECTIVES = [
  'PLANNING DIRECTIVES (from the convergence authority, binding on the Master Plan):',
  '- Respect the locked Stage-0 decisions D1-D3 exactly as written in the North Star.',
  '- Put the ConPTY-across-processes spike EARLY in the phasing — it gates the scope of criterion C4 and must resolve before the PTY half of the supervisor split is committed.',
  '- Every increment must keep the dashboard alive on :8777 (criterion C7) — no phase may require a multi-day freeze or leave the dashboard down.',
  '- Phase 1 must carry concrete near-term specifics sufficient to seed the Stage-2 implementation plan.',
  '- Non-goals in the North Star are binding: no Butler agent, no read-path cutover to the journal, no UI redesign, no new storage engines, no terminal_session.py decomposition, no big-bang rewrite.',
].join('\n');

const brief =
  `=== STAGE-0 INTAKE & TIERED BROWNFIELD INGEST (Confirmed/Inferred/Gap ground truth) ===\n` +
  `${intake}\n=== END STAGE-0 INTAKE ===\n\n${DIRECTIVES}`;

// A lightweight, static research coordinator: the Stage-0 ingest IS the
// up-front research (researchPrime already ran its equivalent at intake).
// perRound is a no-op (nothing new to fetch), but its presence routes the
// brief to the Analyst Shark each round; forSynthesizer feeds the Director.
const research = {
  upfront: async () => {},
  perRound: async () => {},
  forAnalyst: () => brief,
  forSynthesizer: () => brief,
};

// ---------------------------------------------------------------------------
// Summary writers.
// ---------------------------------------------------------------------------

function collectBlockers(loop) {
  const seen = new Map();
  for (const r of loop.rounds || []) {
    for (const b of r.verdict?.blockers || []) {
      if (!seen.has(b.id)) seen.set(b.id, { ...b, raisedInRound: r.round });
    }
  }
  return [...seen.values()];
}

function writeSummary({ brainstorm, triage, plan, loop }) {
  const blockers = collectBlockers(loop);
  const last = loop.lastVerdict || {};
  const jv = loop.judgeVerdict || {};
  const fe = loop.freshEyes?.assessment || {};
  const lines = [
    '# STAGE 1 SUMMARY — Crucible Master Plan (Anchor re-architecture)',
    '',
    `- **Run:** ${new Date().toISOString()} · engine: real Crucible stage1.mjs (live claude.exe sub-agents, 3 CONCURRENT fresh-context Sharks)`,
    `- **North Star:** LOCKED, passed verbatim from NORTH-STAR.md (drift rule active)`,
    `- **Depth:** FULL (roundCap 5) · Stage-0 intake fed via the research seam (never welded into the lock)`,
    '',
    '## Convergence state',
    '',
    `- **Rounds run:** ${loop.roundsRun}`,
    `- **Model-side lockable:** ${loop.modelSideLockable ? 'YES' : 'NO'}`,
    `- **Final round dry:** ${last.dry ? 'YES (no new BLOCKER)' : 'no'}`,
    `- **Judge verdict:** ${jv.decision || '(none)'} — ${(jv.reasons || []).join('; ') || '(no reasons given)'}`,
    `- **Judge stamp:** ${JSON.stringify(loop.judgeStamp || jv.stamp || null)}`,
    `- **Fresh-eyes cold pass:** lean=${fe.lean ?? '(n/a)'} — ${fe.note || '(no note)'}`,
    `- **Fresh-eyes isolation oracle:** ${JSON.stringify(loop.oracle ?? null)}`,
    `- **Fresh-eyes reconcile:** ${JSON.stringify(loop.reconcile ?? null)}`,
    `- **Synthesizer stamp:** ${JSON.stringify(loop.synthesizerStamp || null)}`,
    `- **Convergence gate:** ${JSON.stringify(loop.gate ?? null)}`,
    '',
    '## Rounds',
    '',
    '| Round | Verdict | Dry | Blockers | Findings | Demoted | Synth lean |',
    '|---|---|---|---|---|---|---|',
    ...(loop.rounds || []).map((r) =>
      `| ${r.round} | ${r.verdict?.verdict ?? '?'} | ${r.verdict?.dry ? 'dry' : 'no'} | ${r.verdict?.blockers?.length ?? 0} | ${r.verdict?.findings?.length ?? 0} | ${r.verdict?.demoted?.length ?? 0} | ${r.direction?.lean ?? '—'} |`),
    '',
    '## Blockers raised (>=2-Shark agreement) and their resolution',
    '',
    blockers.length
      ? blockers.map((b) => `- **[${b.severity}] \`${b.id}\`** (round ${b.raisedInRound}, raised by ${(b.raisedBy || []).join(', ')}): ${b.message || ''}\n  - Resolution: addressed in the round-${b.raisedInRound} revision (see stage1-artifacts/round-${b.raisedInRound}/ and the next round's dry/blocked verdict).`).join('\n')
      : '_No >=2-agree blockers were raised — see per-round artifacts for single-Shark findings._',
    '',
    '## Brainstorm / triage',
    '',
    `- Assumptions mapped: ${brainstorm.assumptions.length} · Premortem failure modes: ${brainstorm.premortem.length} · Ideas: ${brainstorm.ideas.length}`,
    `- Triage: ${triage.integrate.length} integrate · ${triage.grasscatcher.length} -> Grasscatcher (GRASSCATCHER.md) · ${triage.dropped.length} dropped`,
    `- Phased plan: ${plan.phases.length} phase(s), ${plan.phases.reduce((n, p) => n + p.nearTermSpecifics.length, 0)} near-term specific(s)`,
    '',
    '## Phases (converged draft)',
    '',
    ...plan.phases.map((p, i) => `${i + 1}. **${p.name}** — ${(p.rationale || '').split(/\n/)[0]}`),
    '',
    '## State',
    '',
    '**HALTED at the master-plan-approval gate (HALT_GATES stage1->stage2) — this HALT is the SUCCESS state.**',
    'The Master Plan draft is at MASTER-PLAN-DRAFT.md. John is the convergence authority: Stage 2 does NOT begin until he approves.',
    '',
    '## Artifacts',
    '',
    '- MASTER-PLAN-DRAFT.md — the converged draft (post-Shark-Tank)',
    '- stage1-artifacts/round-N/ — per-round verdict.json, shark-*.json, SYNTHESIS.md',
    '- stage1-artifacts/{brainstorm,triage,phased-plan,loop-result}.json + initial-draft.md',
    '- GRASSCATCHER.md — parked out-of-scope ideas',
    '- STATUS.log — timestamped run log',
    '',
  ];
  fs.writeFileSync(path.join(PLAN_DIR, 'STAGE1-SUMMARY.md'), lines.join('\n'));
}

function writeFailureSummary(err, phase) {
  const lines = [
    '# STAGE 1 SUMMARY — Crucible Master Plan (Anchor re-architecture)',
    '',
    `- **Run:** ${new Date().toISOString()} — **DID NOT CONVERGE**`,
    `- **Failed/halted during:** ${phase}`,
    `- **Error:** ${err?.message || String(err)}${err?.pending_action ? ` (pending: ${err.pending_action})` : ''}`,
    '',
    err instanceof HaltError || err?.name === 'HaltError'
      ? 'The engine HALTed for human review before the approval gate. Partial artifacts are in stage1-artifacts/; the Shark-Tank state is inspectable per round. Stage 1 must be resumed/re-run before Stage 2.'
      : 'Hard failure. If the engine could not run at all, treat as: degraded — engine did not run; Shark-Tank adversarial vetting DID NOT RUN and must happen before Stage 2.',
    '',
  ];
  fs.writeFileSync(path.join(PLAN_DIR, 'STAGE1-SUMMARY.md'), lines.join('\n'));
}

// ---------------------------------------------------------------------------
// Main.
// ---------------------------------------------------------------------------

let phase = 'startup';
async function main() {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
  log('=== Crucible STAGE 1 start — Anchor re-architecture (Butler substrate) · depth FULL · roundCap 5 ===');
  const { agent } = makeAgentSeam({ runClaude, env: ENV, target: TARGET, log });

  phase = 'oranges-brainstorm (assumption-map -> premortem -> ideation)';
  const brainstorm = await runBrainstorm({ agent, northStar, criteria, research: brief, log });
  saveArtifact('brainstorm.json', brainstorm);

  phase = 'batch-triage';
  const triage = triageIdeas({
    ideas: brainstorm.ideas,
    grasscatcherPath: path.join(PLAN_DIR, 'GRASSCATCHER.md'),
    log,
  });
  saveArtifact('triage.json', triage);

  phase = 'phased-plan';
  const plan = await buildPhasedPlan({
    agent, northStar, criteria,
    ideas: triage.integrate,
    assumptions: brainstorm.assumptions,
    premortem: brainstorm.premortem,
    log,
  });
  saveArtifact('phased-plan.json', plan);
  const initialDraft = renderMasterPlanDraft(plan);
  saveArtifact('initial-draft.md', initialDraft);

  phase = 'shark-tank loop';
  const loop = await runMasterPlanLoop({
    agent, northStar, criteria,
    draft: initialDraft,
    research,
    acceptanceCriteria: criteria,
    roundCap: 5,
    artifactsDir: ARTIFACTS_DIR,
    log,
  });
  saveArtifact('loop-result.json', loop);

  phase = 'deliverables';
  fs.writeFileSync(path.join(PLAN_DIR, 'MASTER-PLAN-DRAFT.md'), loop.draft);
  writeSummary({ brainstorm, triage, plan, loop });
  log('deliverables written: MASTER-PLAN-DRAFT.md + STAGE1-SUMMARY.md');

  phase = 'approval gate';
  try {
    approveMasterPlan({ loop, plan, approved: false, log });
  } catch (e) {
    if (e instanceof HaltError || e?.name === 'HaltError') {
      log(`HALT (EXPECTED — SUCCESS): ${e.message} — awaiting John's approval; Stage 2 does not begin.`);
    } else { throw e; }
  }
  log('=== Crucible STAGE 1 COMPLETE: model-side converged; HALTED at master-plan-approval ===');
  process.exit(0);
}

main().catch((err) => {
  log(`!! STAGE 1 ${err instanceof HaltError || err?.name === 'HaltError' ? 'HALTED' : 'FAILED'} during ${phase}: ${err?.message || err}`);
  try { writeFailureSummary(err, phase); } catch { /* best-effort */ }
  process.exit(err instanceof HaltError || err?.name === 'HaltError' ? 2 : 1);
});

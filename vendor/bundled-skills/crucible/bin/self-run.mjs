// self-run.mjs — Crucible's dogfood self-run + productionization entrypoint (Wave 11).
//
// The dogfood self-run drives the WHOLE engine end-to-end (Stage 0 → 1 → 2) over a
// fixture intent, then runs the 5-gate Skill Productionization Checklist over the
// evidence it produced. It is the wave's runnable entrypoint AND real executed source
// (it satisfies Foreman's vacuous-GREEN guard — the wave's tests import + exercise it).
//
// It proves, in one pass, the three things IMPLEMENTATION-PLAN Wave 11 requires:
//   1. CONVERGENCE — the Shark-Tank loop tallies a REAL finding in one round and a
//      SUBSEQUENT round is dry (no new blood). Proven from the loop's own round log,
//      not asserted.
//   2. A USER-GATE HALT + RESUME — the Master-Plan approval gate HALTs for the human
//      (the convergence authority); the run persists a Crucible checkpoint (Foreman's
//      durable atomic write) with the exact pending action, then RESUMES from it after
//      re-validating it on read. This is the §8 autonomous-between-gates contract.
//   3. A ZERO-HALT DOC-TRIO — Stage 2 emits the Foreman doc-trio + foreman.config.json
//      into a DEDICATED ISOLATED output dir and gates against THAT dir with Foreman's
//      real `locate-plan.mjs` (exit 0). The isolated dir matters: emitting into a dir
//      that already holds several plan-ish *.md files (e.g. Crucible's own repo root)
//      risks `locateDocs`'s ambiguous/multi-role HALT — a fresh dir with exactly the
//      named trio + config resolves via config, HALT-free by construction.
//
// SUBSTRATE: the dogfood uses a deterministic SCRIPTED agent (no live model, no
// subprocess, no billing) so the gate (`node --test`) is reproducible. The same
// orchestration runs on the LIVE seam when CRUCIBLE_AGENT_LIVE=1 — the CLI then wires the
// W6 CROSS-FAMILY role-routed agent (`buildLiveCrucibleAgent` from bin/enhanced.mjs): the
// verification seats (shark / judge) dispatch to a real Gemini `agy -p` backend while the
// steering / drafting seats (synthesizer / stage authors / default) stay on Claude — the
// machine-wide 5:1 split. The orchestration is identical; only the per-role transport
// differs (and a down/unattested Gemini seat HALTs honestly — it is never self-reviewed on
// Claude). The injected-`agent` seam is preserved so tests stub it.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  HaltError,
  newCrucibleCheckpoint,
  writeCheckpointAtomic,
  readCheckpoint,
} from './crucible-lib.mjs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage0 } from './stage0.mjs';
import {
  runBrainstorm,
  triageIdeas,
  buildPhasedPlan,
  renderMasterPlanDraft,
  runMasterPlanLoop,
  approveMasterPlan,
} from './stage1.mjs';
import { runStage2 } from './stage2.mjs';
import { detectDrift } from './gates.mjs';
import { runProductionizationChecklist, renderChecklist } from './checklist.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// The fixture intent the dogfood plans (a small, self-describing greenfield ask).
// ---------------------------------------------------------------------------

export const SELF_RUN_INTENT =
  'Plan a small standalone tool that turns a project intent into a vetted, ' +
  'Foreman-ready implementation plan that locate-plan accepts with zero HALTs.';

const SELF_RUN_NORTH_STAR =
  'SELF-RUN-NS: emit a vetted, Foreman-ready doc-trio that locate-plan accepts with zero HALTs, each wave carrying testable acceptance criteria.';

const SELF_RUN_CRITERIA = [
  'emits a zero-HALT Foreman-ready doc-trio',
  'every wave carries a testable done-when',
  'the loop converges and the user approves',
];

const SELF_RUN_ACCEPTANCE = [
  'every wave has a done-when',
  'the doc-trio passes locate-plan with zero HALTs',
];

// The Stage-2 wave decomposition the scripted agent returns — two waves, the first
// non-trivial (carries G/W/T), both with a done-when (so the emission is well-formed).
const SELF_RUN_DECOMP = [
  {
    title: 'Engine skeleton',
    intent: 'stand up the Node engine importing Foreman primitives',
    deliverables: ['package.json', 'bin/lib.mjs', 'a Foreman import smoke-test'],
    dependsOn: null,
    doneWhen: 'node --test test/ passes the import smoke-test',
    nonTrivial: true,
    gwt: [{ given: 'the imported primitives', when: 'the smoke test runs', then: 'every primitive is a function' }],
  },
  {
    title: 'Docs layer',
    deliverables: ['README.md'],
    dependsOn: 'Engine skeleton',
    doneWhen: 'the README renders the orientation',
    nonTrivial: false,
    gwt: [],
  },
];

// ---------------------------------------------------------------------------
// The deterministic scripted agent (the dogfood substrate).
//
// Label-routed, mirroring the per-stage test stubs: it drives a one-block→fix→dry
// Shark-Tank loop (a real finding in round 1, dry in round 2) for BOTH stage loops,
// and returns schema-shaped objects for every stage step.
// ---------------------------------------------------------------------------

/**
 * Build the scripted dogfood agent. `blockedUntilRound` controls how many rounds the
 * Skeptic + Contrarian agree on a BLOCKER (default 2 ⇒ round 1 blocks, round 2 dry —
 * a genuine convergence: finding tallied → subsequent dry round).
 */
export function makeScriptedSelfRunAgent({ blockedUntilRound = 2 } = {}) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';

    // --- Stage 0 framing (greenfield) ---
    if (label === 'stage0:framing') {
      return {
        northStar: SELF_RUN_NORTH_STAR,
        criteria: SELF_RUN_CRITERIA,
        nonGoals: ['no pedagogy/education', 'not a code builder'],
        riskTaxonomy: [{ risk: 'scope drift', mitigation: 'lock the North Star; track every change' }],
        foresightBrief: 'capture per-wave acceptance criteria now so Stage 2 stays Foreman-ready.',
      };
    }

    // --- Stage 1 brainstorm (assumption-map → premortem → ideate) ---
    if (label === 'stage1:assumptions') {
      return { assumptions: [{ id: 'A1', assumption: 'the machine gate is Foreman locate-plan', criticality: 'high', basis: 'design' }] };
    }
    if (label === 'stage1:premortem') {
      return { failureModes: [{ id: 'F1', mode: 'the doc-trio HALTs locate-plan', cause: 'no test-command line', assumptionRef: 'A1', mitigation: 'render test-command + contiguous ## Wave N' }] };
    }
    if (label === 'stage1:ideas') {
      return {
        ideas: [
          { id: 'I1', idea: 'render a contiguous ## Wave N + a single early test-command line', traces_to_north_star: 'yes', criterion: 'C1', tag: 'refinement' },
          { id: 'I2', idea: 'ship a cosmetic telemetry dashboard theme', traces_to_north_star: 'no', tag: 'out-of-scope', note: 'cosmetic — does not serve a criterion' },
        ],
      };
    }
    if (label === 'stage1:phased-plan') {
      return {
        summary: 'phased toward a zero-HALT, Foreman-ready doc-trio',
        phases: [
          { name: 'Engine', rationale: 'import foreman-lib; never fork', nearTermSpecifics: ['emit contiguous ## Wave N', 'declare a test-command'], deferred: ['optional RTM/viz/SUMMARY docs'] },
        ],
      };
    }
    if (label.startsWith('stage1:revise')) {
      return { draft: `# Plan (revised)\n\n**North Star:** ${SELF_RUN_NORTH_STAR}\n`, changelog: ['addressed the blocking finding'] };
    }

    // --- Stage 2 decomposition ---
    if (label === 'stage2:decompose') return { waves: SELF_RUN_DECOMP };

    // --- Shark Tank: a real finding in early rounds, dry thereafter ---
    if (label.startsWith('shark:')) {
      const parts = label.split(':'); // shark:Role:rN
      const role = parts[1];
      const round = parseInt(String(parts[2] || 'r0').slice(1), 10) || 0;
      if (round < blockedUntilRound && (role === 'Skeptic' || role === 'Contrarian')) {
        // Two Sharks naming the SAME topic ⇒ normalizes to one id ⇒ ≥2-agree BLOCKER.
        return {
          answerable: 'yes',
          findings: [{
            severity: 'BLOCKER', topic: 'wave acceptance criteria underspecified', section: 'waves',
            tag: 'refinement', traces_to_north_star: 'yes', criterion: 'C1',
            message: 'a wave lacks a testable done-when',
          }],
        };
      }
      return { answerable: 'yes', findings: [] };
    }

    // --- Director / fresh-eyes / Judge ---
    if (label.includes('fresh-eyes')) return { lean: 'lockable', concerns: [], note: 'cold read concurs — no lock-blocking problem' };
    if (label.startsWith('synthesizer:direct')) return { lean: 'lockable', openDisputes: [], riskRegister: [], probingBrief: 'press the well-formedness gate', suggestions: ['capture acceptance criteria up front'] };
    if (label.startsWith('judge:')) return { decision: 'CONVERGED', reasons: ['dry round; no open blocker; fresh-eyes concurs'] };

    return {};
  }
  agent.calls = calls;
  return agent;
}

// ---------------------------------------------------------------------------
// The dogfood self-run orchestration.
// ---------------------------------------------------------------------------

/** Pull the convergence proof (finding round → subsequent dry round) from a loop result. */
function convergenceFromLoop(loop) {
  const rounds = Array.isArray(loop?.rounds) ? loop.rounds : [];
  const findingEntry = rounds.find((r) => (r.verdict?.blockers?.length || 0) > 0);
  const dryEntry = rounds.find((r) => r.verdict?.dry === true && (!findingEntry || r.round > findingEntry.round));
  return {
    proved: !!(findingEntry && dryEntry),
    findingRound: findingEntry ? { round: findingEntry.round, blockers: findingEntry.verdict.blockers.length } : null,
    dryRound: dryEntry ? { round: dryEntry.round } : null,
  };
}

/**
 * Run the dogfood self-run end-to-end and return its transcript + the 5-gate checklist.
 *
 * @param {object}   o
 * @param {Function} o.agent                       the agent seam (scripted by default; live when wired)
 * @param {string}   o.outputDir                   the DEDICATED ISOLATED dir the doc-trio is emitted into
 * @param {?string} [o.checkpointPath=null]        where the HALT/resume checkpoint is written (defaults under outputDir)
 * @param {string}  [o.intent=SELF_RUN_INTENT]
 * @param {?string} [o.artifactsDir=null]          Shark-Tank + gate artifacts dir
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<{transcript:object, checklist:object, ok:boolean}>}
 */
export async function dogfoodSelfRun({
  agent,
  outputDir,
  checkpointPath = null,
  intent = SELF_RUN_INTENT,
  artifactsDir = null,
  log = () => {},
} = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError('dogfoodSelfRun requires an agent() seam', 'pass makeScriptedSelfRunAgent() or a live makeAgentSeam().agent');
  }
  if (!outputDir) throw new HaltError('dogfoodSelfRun requires an outputDir', 'pass a dedicated isolated output directory for the emitted doc-trio');
  const dir = path.resolve(outputDir);
  fs.mkdirSync(dir, { recursive: true });
  const cpPath = checkpointPath || path.join(dir, 'crucible-checkpoint.json');

  // === Stage 0 — frame the greenfield intent and lock the North Star (approved). ===
  const stage0 = await runStage0({ intent, input: { kind: 'greenfield' }, agent, approved: true, log });
  const northStar = stage0.lock.northStar;
  const criteria = stage0.lock.criteria;
  log(`self-run: Stage 0 locked the North Star (drift detection active=${stage0.lock.driftDetectionActive})`);

  // === Stage 1 — brainstorm → triage → phased plan → Shark-Tank loop (to convergence). ===
  const brainstorm = await runBrainstorm({ agent, northStar, criteria, log });
  const triage = triageIdeas({ ideas: brainstorm.ideas, log });
  const phased = await buildPhasedPlan({
    agent, northStar, criteria,
    ideas: triage.integrate, assumptions: brainstorm.assumptions, premortem: brainstorm.premortem, log,
  });
  const loop = await runMasterPlanLoop({
    agent, northStar, criteria, draft: renderMasterPlanDraft(phased),
    acceptanceCriteria: SELF_RUN_ACCEPTANCE, artifactsDir, log,
  });
  const convergence = convergenceFromLoop(loop);
  log(`self-run: convergence proved=${convergence.proved} (finding r${convergence.findingRound?.round} → dry r${convergence.dryRound?.round})`);

  // === The user-gate HALT + checkpoint + resume (§8 autonomous-between-gates). ===
  // First cross WITHOUT approval — the user is the convergence authority, so it HALTs.
  let halt = null;
  try {
    approveMasterPlan({ loop, plan: phased, approved: false, log });
  } catch (e) {
    if (!(e instanceof HaltError)) throw e;
    halt = e;
  }
  if (!halt) throw new HaltError('self-run expected the Master-Plan approval gate to HALT unapproved', 'the user-gate HALT did not fire — the gate is broken');

  // Persist a Crucible checkpoint at the HALT (Foreman's durable atomic write) with the
  // exact pending action, then RESUME by re-reading + re-validating it.
  const cp = newCrucibleCheckpoint({
    plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'),
    total_waves: phased.phases.length,
    stage: 'stage1',
    phase: halt.pending_action,
    round: loop.roundsRun,
  });
  cp.status = 'halted';
  cp.pending_action = halt.pending_action;
  cp.last_verdict = 'HALT';
  writeCheckpointAtomic(cpPath, cp);
  const reloaded = readCheckpoint(cpPath); // validates on read — throws (HALT) if torn/invalid
  const checkpointValidated = reloaded.status === 'halted' && reloaded.pending_action === halt.pending_action;

  // The human approves → resume from the checkpoint and cross the gate.
  const approval = approveMasterPlan({ loop, plan: phased, approved: true, log });
  const masterPlan = approval.masterPlan;
  const checkpointResume = {
    halted: true,
    gate: halt.pending_action,
    pendingAction: halt.pending_action,
    checkpointPath: cpPath,
    validated: checkpointValidated,
    resumed: approval.approved === true,
  };
  log(`self-run: HALTed at "${halt.pending_action}", checkpointed, and resumed (validated=${checkpointValidated})`);

  // === Post-lock drift: detection is active; a surfaced out-of-scope item is TRACKED. ===
  // Drift detection runs only AFTER the lock (Stage-0 gaps are exempt). Exercise it on a
  // representative post-lock surfaced idea — it must be tracked (flagged + routed), never
  // silently absorbed.
  const surfacedIdea = { severity: 'MINOR', tag: 'out-of-scope', traces_to_north_star: 'no', topic: 'a cosmetic dashboard theme surfaced after the lock' };
  const driftResult = detectDrift(surfacedIdea, { locked: true });
  const drift = {
    active: driftResult.active === true,
    surfaced: [{ topic: surfacedIdea.topic, tier: driftResult.tier, action: driftResult.action, resolution: driftResult.resolution, tracked: driftResult.drift === true }],
    untracked: driftResult.drift === true ? 0 : 1,
  };

  // === Stage 2 — emit the doc-trio + config into the ISOLATED dir; gate against it. ===
  const stage2 = await runStage2({
    agent, northStar, masterPlan, criteria, outputDir: dir,
    title: 'Crucible self-run target', summary: 'Emitted by the Crucible dogfood self-run.',
    acceptanceCriteria: SELF_RUN_ACCEPTANCE, approved: true, artifactsDir, log,
  });
  const gate = stage2.handoff.gate;
  const waves = stage2.waves;
  log(`self-run: Stage 2 emitted ${waves.length} wave(s); well-formedness gate pass=${gate.pass} (exit ${gate.status})`);

  // === The per-role independence stamps (degraded-and-stamped in Default mode). ===
  const stamps = [loop.synthesizerStamp, loop.judgeStamp].filter(Boolean);

  const transcript = {
    intent,
    northStar,
    criteria,
    stages: { stage0: 'locked', stage1: 'approved', stage2: 'handed-off' },
    convergence,
    haltResume: checkpointResume,
    drift,
    stamps,
    docTrio: { dir: stage2.docTrio.dir, configPath: stage2.docTrio.configPath, files: stage2.docTrio.files },
    gate: { pass: gate.pass, status: gate.status, total_waves: gate.report?.total_waves ?? null },
    waves: waves.map((w) => ({ n: w.n, title: w.title, doneWhen: w.doneWhen })),
  };

  const checklist = runProductionizationChecklist({
    wellFormedness: gate,
    waves,
    convergence,
    approval,
    drift,
    checkpointResume,
    stamps,
  });
  log(renderChecklist(checklist));

  return { transcript, checklist, ok: checklist.allPass };
}

// ---------------------------------------------------------------------------
// The CLI entrypoint.
//
// `node bin/self-run.mjs [outputDir]` runs the dogfood. Default substrate is the
// deterministic scripted agent (no model, no billing); set CRUCIBLE_AGENT_LIVE=1 to
// drive the SAME orchestration with the W6 CROSS-FAMILY role-routed agent — genuine
// Gemini `agy -p` Sharks + Judge (verification) and Claude for steering/drafting (the
// 5:1 split). Exit 0 on a full 5/5 checklist pass, 1 otherwise.
// ---------------------------------------------------------------------------

export async function main(argv = process.argv.slice(2), { env = process.env, log = (m) => process.stdout.write(m + '\n') } = {}) {
  const outputDir = argv[0] || fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-self-run-'));
  const live = env.CRUCIBLE_AGENT_LIVE === '1';
  // LIVE: build the cross-family role-routed agent (shark/judge → Gemini, synth/default →
  // Claude). It runs the self-review routing guard up front and instruments the reached-
  // family tracker + the ≤2–3 Gemini concurrency cap; a down/unattested Gemini seat HALTs
  // (never a silent Claude self-review). Scripted default stays deterministic (no model).
  let tracker = null;
  let agent;
  if (live) {
    const built = await buildLiveCrucibleAgent({ env, target: HERE, log });
    agent = built.agent;
    tracker = built.tracker;
  } else {
    agent = makeScriptedSelfRunAgent();
  }
  log(`Crucible dogfood self-run — substrate: ${live ? 'LIVE cross-family (Gemini shark/judge, Claude synth/default)' : 'scripted (deterministic)'} — output: ${outputDir}`);

  const { transcript, checklist } = await dogfoodSelfRun({ agent, outputDir, log });
  log('');
  log(renderChecklist(checklist));
  log('');
  log(`doc-trio: ${transcript.docTrio.dir}`);
  log(`well-formedness gate: pass=${transcript.gate.pass} (exit ${transcript.gate.status}, ${transcript.gate.total_waves} wave[s])`);
  log(`convergence: finding r${transcript.convergence.findingRound?.round} → dry r${transcript.convergence.dryRound?.round}; HALT/resume at "${transcript.haltResume.pendingAction}"`);
  // Substrate provenance is DERIVED from the families ACTUALLY reached (never hardcoded): a
  // genuine cross-family run reports [claude, gemini]; a Gemini-absent run honestly reports [claude].
  if (live && tracker) log(`substrate families reached: [${tracker.families().join(', ')}] (verification seats = Gemini; steering/drafting = Claude)`);
  return checklist.allPass ? 0 : 1;
}

// Run only when invoked directly (never on import — tests import the orchestration).
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then((code) => process.exit(code)).catch((e) => {
    process.stderr.write(`HALT: ${e.message}${e.pending_action ? ` (pending: ${e.pending_action})` : ''}\n`);
    process.exit(e instanceof HaltError ? 3 : 2);
  });
}

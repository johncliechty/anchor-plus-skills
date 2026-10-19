// src/stage0-plan.mjs — Wave 9: literature-review's THIN Stage-0 PLAN-phase consumer.
//
// Stage-0 wires literature-review to the plan-first front-end with NO derivation
// logic of its own:
//
//   shared module (brownfieldIntake: ingest -> grounded summary -> ONE bounded
//   derive -> PlanArtifact)
//     -> shared renderer (renderPlanPresentation: prose plan body + advisory sidecar)
//       -> the FROZEN researchPrime one-shot gate (bin/plan-gate.mjs machinery via
//          bin/two-gate.mjs, ZERO edits: APPROVE proceeds / EDIT accepted once and
//          re-hashes / ABORT halts / no response HALTs / headless approvalProvider
//          resolves without any isTTY halt)
//         -> on APPROVE, the shared resolveApprovedPlan: APPROVE-verbatim executes
//            the already-derived artifact with zero parse calls; APPROVE-with-EDITs
//            runs the ONE bounded re-derive parse, which RUNs or fail-to-ABORTs with
//            a stamped reason and NEVER re-presents the gate.
//
// Stage-0 is a TRUE stage: it fully initializes PRISMA state and serializes the
// ENTIRE pipeline state (src/pipeline-state.mjs) at the HALT boundary, BEFORE the
// gate can resolve — so a run with no gate response yet halts durably and resumes
// later with ZERO additional Gandalf/derive calls. This module keeps its hands off
// src/search.mjs entirely — no dependency on it exists here; snowball runs only
// when the caller sees stage0AllowsExecution(result) === true.
//
// Frozen-gate access follows the pinned Wave-1 resolution rules
// (docs/DECISION-RECEIPT-shared-location.md): researchPrime via RP_ROOT or the
// deployed-skill convention, realpath'd BEFORE import, then contract.TRIO_ROOT for
// the shared module. The `skill: 'literature-review'` governance tag is admitted via
// the public governance.registerExtension() seam — a supported caller-side call,
// never an edit to a researchPrime file.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import {
  initializePipelineState,
  markPlanApproved,
  markPlanAborted,
  writePipelineState,
  readPipelineState,
  PIPELINE_STATUSES,
} from './pipeline-state.mjs';

export const STAGE0_PLAN_VERSION = 'litreview-stage0-plan/1';

/** The gate-body plan version tag Stage-0 stamps on the frozen gate's plan object. */
export const STAGE0_GATE_PLAN_VERSION = 'litreview-brownfield-plan/stage0-1';

/** Stage-0 outcome statuses. Only RUN unlocks snowball. */
export const STAGE0_STATUSES = Object.freeze({
  RUN: 'RUN',
  HALTED: 'HALTED',
  ABORTED: 'ABORTED',
  FAILED: 'FAILED',
});

/** Default durable file names inside the Stage-0 run directory. */
export const PIPELINE_STATE_FILENAME = 'pipeline-state.json';
export const PLAN_ARTIFACT_FILENAME = 'plan-artifact.json';

// ── Pinned trio resolution (the Wave-1 decision-receipt rules, runtime side) ─────────

let rpRootCache = null;

/** Resolve the researchPrime checkout (RP_ROOT override, else deployed-skill symlink, realpath'd). */
export function resolveResearchPrimeRoot() {
  if (rpRootCache) return rpRootCache;
  const candidate = process.env.RP_ROOT
    ? path.resolve(process.env.RP_ROOT)
    : path.join(os.homedir(), '.claude', 'skills', 'researchPrime');
  let root = candidate;
  try {
    root = fs.realpathSync(candidate);
  } catch {
    // fall through to the existence check with the un-realpath'd candidate
  }
  if (!fs.existsSync(path.join(root, 'bin', 'two-gate.mjs'))) {
    throw new Error(
      `stage0-plan: researchPrime not found at ${root} — set RP_ROOT to a researchPrime checkout ` +
        '(Stage-0 consumes its frozen bin/two-gate.mjs plan-review gate unmodified)',
    );
  }
  rpRootCache = root;
  return root;
}

async function importRpModule(rel) {
  return import(pathToFileURL(path.join(resolveResearchPrimeRoot(), rel)).href);
}

let gateModulesCache = null;

/** The frozen gate machinery + governance seam (imported, never edited). */
async function loadGateModules() {
  if (!gateModulesCache) {
    const [twoGate, governance, core] = await Promise.all([
      importRpModule('bin/two-gate.mjs'),
      importRpModule('bin/governance.mjs'),
      importRpModule('bin/trio-core/contract-core.mjs'),
    ]);
    gateModulesCache = { twoGate, governance, HaltError: core.HaltError };
  }
  return gateModulesCache;
}

let sharedModulesCache = null;

/** The pinned shared brownfield-intake front-end (resolved through RP's own TRIO_ROOT pin). */
async function loadSharedModules() {
  if (!sharedModulesCache) {
    const contract = await importRpModule('bin/contract.mjs');
    const baseUrl = new URL('trio-shared/brownfield-intake/index.mjs', contract.TRIO_ROOT);
    const [entry, renderer, rederive, validate] = await Promise.all([
      import(baseUrl.href),
      import(new URL('renderPlanProse.mjs', baseUrl).href),
      import(new URL('rederiveFromProse.mjs', baseUrl).href),
      import(new URL('validatePlanArtifact.mjs', baseUrl).href),
    ]);
    sharedModulesCache = { entry, renderer, rederive, validate };
  }
  return sharedModulesCache;
}

/**
 * Build a headless ApprovalProvider (token / policy-grant / replay) with the TTY route
 * removed, for hosts with no human channel — resolves through researchPrime's own
 * approval-provider module, unmodified.
 *
 * @param {object} options
 * @param {string} options.runDir
 * @param {string} [options.token] A signed approval token.
 * @param {string} [options.policyGrantIdentity] Identity for an explicit policy grant.
 * @param {object} [options.replayFixture] A replayed prior decision fixture.
 * @returns {Promise<object>} an ApprovalProvider with ttyAllowed: false
 */
export async function buildHeadlessApproval({ runDir, token, policyGrantIdentity, replayFixture } = {}) {
  const approval = await importRpModule('bin/approval-provider.mjs');
  return new approval.ApprovalProvider({
    runDir,
    ttyAllowed: false,
    ...(token ? { token } : {}),
    ...(policyGrantIdentity ? { policyGrant: { identity: policyGrantIdentity } } : {}),
    ...(replayFixture ? { replayFixture } : {}),
  });
}

/**
 * The single predicate the pipeline uses to unlock snowball: ONLY a Stage-0 result
 * that reached RUN with a bound execution artifact may proceed past the plan phase.
 * HALTED, ABORTED, and FAILED results all block src/search.mjs.
 *
 * @param {object|null|undefined} stage0Result
 * @returns {boolean}
 */
export function stage0AllowsExecution(stage0Result) {
  return (
    stage0Result?.status === STAGE0_STATUSES.RUN &&
    stage0Result.executionArtifact !== null &&
    typeof stage0Result.executionArtifact === 'object'
  );
}

/** Default bounded parse: no adapter bound -> the re-derive fail-to-ABORTs honestly. */
function noParseBound() {
  throw new Error(
    'no bounded re-derive parse adapter is bound (APPROVE-with-EDITs requires live seats); ' +
      'nothing was re-derived and nothing was fabricated',
  );
}

/** Build the Gate-2 decision channel from the declarative gate options. */
function buildPromptGate2(gate, capturePresentation) {
  if (typeof gate.promptGate2 === 'function') {
    return async (presented) => {
      capturePresentation(presented);
      return gate.promptGate2(presented);
    };
  }
  if (typeof gate.decision === 'string') {
    // Declarative one-shot decision: EDIT means "accept the edit once, then APPROVE
    // the re-presented plan" (the gate's bounded-EDIT round-trip); APPROVE/ABORT are
    // constant. Anything else is presented verbatim and the gate halts on it.
    const sequence =
      gate.decision === 'EDIT' ? ['EDIT', 'APPROVE'] : [gate.decision];
    let call = 0;
    return async (presented) => {
      capturePresentation(presented);
      const decision = call < sequence.length ? sequence[call] : sequence[sequence.length - 1];
      call += 1;
      return decision;
    };
  }
  // No decision channel at all: the run HALTs at the gate (durable HALT-RECORD),
  // resumable later from the serialized pipeline state.
  return async (presented) => {
    capturePresentation(presented);
    return undefined;
  };
}

/**
 * Run literature-review's Stage-0 PLAN phase: derive (or resume) the PlanArtifact,
 * present it to the FROZEN one-shot gate, and resolve what — if anything — may
 * execute. src/search.mjs is never touched here; the caller gates snowball on
 * stage0AllowsExecution(result).
 *
 * Resume: when the runDir already holds a serialized pipeline state with status
 * HALTED, the plan artifact, plan body, and grounding cache are loaded from that
 * state and NO intake (Gandalf/derive) call is spent again.
 *
 * @param {object} options
 * @param {string} options.runDir Durable Stage-0 run directory (gate records + state).
 * @param {string} [options.statePath] Pipeline-state file (default runDir/pipeline-state.json).
 * @param {string} [options.planArtifactPath] Plan-artifact file (default runDir/plan-artifact.json).
 * @param {object} [options.intake] Passed to the shared brownfieldIntake entry:
 *   { roots, requests, intent, seeds, budgetTokens, autoTruncate, summaryMaxTokens, maxOutputChars }.
 * @param {Function} [options.summarize] The Gandalf summarize adapter (content routes).
 * @param {object} [options.grounding] Quote-grounding functions ({ buildNormalizedView, groundQuote }).
 * @param {Function} [options.derive] The ONE bounded derive adapter.
 * @param {Function} [options.parse] The ONE bounded re-derive parse (APPROVE-with-EDITs);
 *   when absent, an edited approval fail-to-ABORTs honestly instead of running.
 * @param {object} [options.gate] Gate wiring: { objective, decision, editedProse,
 *   promptGate1, promptGate2, onEditedPlan, approvalProvider, maxEdits }.
 * @param {Function} [options.log]
 * @returns {Promise<object>} the Stage-0 result ({ status, ... }; see STAGE0_STATUSES)
 */
export async function runStage0Plan({
  runDir,
  statePath,
  planArtifactPath,
  intake = {},
  summarize,
  grounding,
  derive,
  parse,
  gate = {},
  log = () => {},
} = {}) {
  if (typeof runDir !== 'string' || runDir.trim() === '') {
    throw new TypeError('runStage0Plan: runDir must be a directory path string');
  }
  fs.mkdirSync(runDir, { recursive: true });
  const stateFile = statePath ?? path.join(runDir, PIPELINE_STATE_FILENAME);
  const artifactFile = planArtifactPath ?? path.join(runDir, PLAN_ARTIFACT_FILENAME);

  const shared = await loadSharedModules();

  // ── 1. PlanArtifact: resume from the serialized HALT boundary, else ONE intake run ──
  let artifact = null;
  let groundedSources = {};
  let planBody;
  let coverageSidecar;
  let route = null;
  let intakeResult = null;
  let state;
  let resumed = false;

  const priorState = readPipelineState(stateFile);
  if (priorState?.status === PIPELINE_STATUSES.HALTED && priorState.plan?.artifact) {
    resumed = true;
    artifact = priorState.plan.artifact;
    planBody = priorState.plan.planBody;
    coverageSidecar = priorState.plan.coverageSidecar ?? null;
    groundedSources = priorState.groundingCache?.sources ?? {};
    route = priorState.route ?? null;
    state = priorState;
    log(`Stage-0 resume: plan artifact loaded from ${stateFile} (zero intake calls spent).`);
  } else {
    intakeResult = await shared.entry.brownfieldIntake({
      ...intake,
      summarize,
      grounding,
      derive,
    });
    route = intakeResult.route;
    if (!intakeResult.ok || intakeResult.artifact === null) {
      return {
        stage0Version: STAGE0_PLAN_VERSION,
        status: STAGE0_STATUSES.FAILED,
        resumed: false,
        route,
        reason: intakeResult.reason,
        intake: intakeResult,
        artifact: null,
        executionArtifact: null,
        state: null,
        statePath: stateFile,
        planArtifactPath: artifactFile,
      };
    }
    artifact = intakeResult.artifact;
    groundedSources = { ...(intakeResult.groundedSources ?? {}) };
    const presentation = shared.renderer.renderPlanPresentation(artifact);
    planBody = presentation.planBody;
    coverageSidecar = presentation.coverageSidecar;
    state = initializePipelineState({
      artifact,
      planBody,
      coverageSidecar,
      groundedSources,
      route,
      truncated: intakeResult.truncated === true,
      truncationStamp: intakeResult.truncationStamp ?? null,
    });
  }

  // ── 2. The HALT boundary: plan artifact + full pipeline state written BEFORE the
  //       gate can resolve, so a no-response run halts durably and resumably. ─────────
  fs.writeFileSync(artifactFile, shared.validate.canonicalStringifyPlanArtifact(artifact) + '\n', 'utf8');
  writePipelineState(stateFile, state);

  // ── 3. The FROZEN one-shot gate (zero edits; skill tag via the public seam) ─────────
  const gateModules = await loadGateModules();
  gateModules.governance.registerExtension('literature-review', () => true);

  const objective =
    gate.objective ?? `literature-review Stage-0 research plan: ${artifact.scope.statement}`;
  const inputs = { objective, planProse: planBody };
  // Pure function of inputs (the gate's EDIT re-hash discipline requires this).
  const buildPlan = ({ inputs: current }) => ({
    planVersion: STAGE0_GATE_PLAN_VERSION,
    body: current.planProse,
  });

  const presentations = [];
  const capturePresentation = (p) => presentations.push(p);
  const onEditedPlan =
    gate.onEditedPlan ??
    (typeof gate.editedProse === 'string'
      ? async (current) => ({ ...current, planProse: gate.editedProse })
      : undefined);

  let gateResult;
  try {
    gateResult = await gateModules.twoGate.runTwoGateMachine(inputs, {
      runDir,
      skill: 'literature-review',
      buildPlan,
      maxEdits: gate.maxEdits ?? 1,
      ...(gate.approvalProvider
        ? { approvalProvider: gate.approvalProvider }
        : {
            promptGate1: gate.promptGate1 ?? (async () => 'APPROVE'),
            promptGate2: buildPromptGate2(gate, capturePresentation),
          }),
      ...(onEditedPlan ? { onEditedPlan } : {}),
    });
  } catch (err) {
    if (err instanceof gateModules.HaltError || err?.name === 'HaltError') {
      const aborted = /decision ABORT/.test(err.message);
      const nextState = aborted
        ? markPlanAborted(state, {
            stamp: 'litreview-stage0/gate-abort/1',
            reason: err.message,
          })
        : state; // still HALTED — resumable
      writePipelineState(stateFile, nextState);
      log(
        aborted
          ? `Stage-0 gate ABORT: ${err.message}`
          : `Stage-0 HALT (no approval yet): ${err.message}`,
      );
      return {
        stage0Version: STAGE0_PLAN_VERSION,
        status: aborted ? STAGE0_STATUSES.ABORTED : STAGE0_STATUSES.HALTED,
        resumed,
        route,
        reason: err.message,
        halt: { reason: err.message },
        intake: intakeResult,
        artifact,
        planBody,
        coverageSidecar,
        presentations,
        executionArtifact: null,
        state: nextState,
        statePath: stateFile,
        planArtifactPath: artifactFile,
      };
    }
    throw err;
  }

  // ── 4. APPROVE resolved: verbatim executes the derived artifact; edits take the ONE
  //       bounded re-derive, which RUNs or fail-to-ABORTs and NEVER re-presents. ──────
  const approvedPlanPath = path.join(runDir, `plan-${gateResult.planHash}.json`);
  const approvedProse = JSON.parse(fs.readFileSync(approvedPlanPath, 'utf8')).body;
  const decision = await shared.rederive.resolveApprovedPlan({
    derivedArtifact: artifact,
    approvedProse,
    groundedSources,
    parse: parse ?? noParseBound,
  });

  if (decision.outcome === 'ABORT') {
    const nextState = markPlanAborted(state, decision.abort);
    writePipelineState(stateFile, nextState);
    log(`Stage-0 re-derive ABORT (stamped, gate NOT re-presented): ${decision.abort.reason}`);
    return {
      stage0Version: STAGE0_PLAN_VERSION,
      status: STAGE0_STATUSES.ABORTED,
      resumed,
      route,
      reason: decision.abort.reason,
      abort: decision.abort,
      decision,
      intake: intakeResult,
      artifact,
      planBody,
      coverageSidecar,
      presentations,
      planHash: gateResult.planHash,
      governanceRecord: gateResult.governanceRecord,
      executionArtifact: null,
      state: nextState,
      statePath: stateFile,
      planArtifactPath: artifactFile,
    };
  }

  const nextState = markPlanApproved(state, {
    planHash: gateResult.planHash,
    approvedPath: decision.path,
  });
  writePipelineState(stateFile, nextState);
  log(`Stage-0 APPROVE (${decision.path}): plan ${gateResult.planHash.slice(0, 12)}… may execute.`);
  return {
    stage0Version: STAGE0_PLAN_VERSION,
    status: STAGE0_STATUSES.RUN,
    resumed,
    route,
    decision,
    intake: intakeResult,
    artifact,
    planBody,
    coverageSidecar,
    presentations,
    planHash: gateResult.planHash,
    governanceRecord: gateResult.governanceRecord,
    executionArtifact: decision.artifact,
    state: nextState,
    statePath: stateFile,
    planArtifactPath: artifactFile,
  };
}

// engine/pipeline.mjs — Wave 1: the orchestrator.
//
// A read-only analysis run, in order:
//
//   1. TOPOLOGY CHECK   — what tree are we allowed to look at (and what did we
//                         exclude)? A junction escaping the root aborts here.
//   2. SNAPSHOT S       — the single time authority, captured ONCE.
//   3. STAGES           — each stage(ctx) returns the uniform envelope; the
//                         write-audit facade is armed with the stage's name so
//                         a blocked write names the culprit.
//   4. PROTECTION       — every actionable finding is filtered BEFORE emission;
//                         withheld paths are logged with the reason.
//   5. SWEEP vs S       — Tier 2 of the tripwire (see engine/snapshot.mjs for
//                         why production drift is not an abort but hermetic
//                         fixture drift is a build failure).
//   6. ENVELOPE         — terminal status = WORST stage status; isClean is
//                         computed, never asserted.
//
// The orchestrator writes NOTHING. Persisting the envelope into reportDir is
// the caller's (Wave 5's archive) job, and reportDir is the tripwire's sole
// exception precisely so that write is legal when it comes.

import { createContext } from './context.mjs';
import { checkTopology } from './topology.mjs';
import { captureSnapshot, ensureHash, sweepSnapshot, applyStaleness } from './snapshot.mjs';
import { makeRunEnvelope, makeStageResult, failedStage, STATUS } from './envelope.mjs';
import { STAGES } from './stages/index.mjs';
import { ConfigParseError } from './config.mjs';
import { WriteAuditViolation } from './write-audit.mjs';
import { markAdvisory, markHeuristic } from './advisory.mjs';
import { stampFindingIds } from './apply/identity.mjs';
import { projectIdentity } from './launch/identity.mjs';

/**
 * Run the staged pipeline over a root.
 *
 * @param {object} opts — everything createContext accepts, plus {stages}
 * @returns {Promise<object>} the run envelope
 */
export async function runPipeline(opts = {}) {
  const stages = opts.stages || STAGES;
  const startedAt = new Date().toISOString();
  const onProgress = opts.onProgress || null;

  // A config parse error is a FAILED STAGE, never a silent fallback to
  // defaults: a malformed .tidy-idy.toml means we do not know what protections
  // the user asked for, and guessing is exactly the behaviour the plan forbids.
  let ctx;
  try {
    ctx = await createContext(opts);
  } catch (err) {
    const isConfig = err instanceof ConfigParseError;
    return makeRunEnvelope({
      runId: opts.runId || null,
      rootPath: opts.rootPath,
      mode: opts.mode || null,
      ruleset: null,
      reportDir: opts.reportDir || null,
      // Even a run that could not build a context knows WHICH folder it failed
      // on — a panel that cannot name the project is a panel nobody can trust.
      identity: projectIdentity({ rootPath: opts.rootPath, git: null }),
      costGate: opts.costGate || null,
      startedAt,
      endedAt: new Date().toISOString(),
      stages: [failedStage(isConfig ? 'config' : 'context', err, {
        note: isConfig ? 'config parse error — the run refuses to fall back to defaults' : 'run context could not be created',
      })],
    });
  }

  return runPipelineWithContext(ctx, { stages, startedAt, onProgress });
}

/** Same pipeline over an already-built ctx (used by the git:null contract test). */
export async function runPipelineWithContext(ctx, {
  stages = STAGES,
  startedAt = new Date().toISOString(),
  /** Optional async ({ step, message, stage?, findingsSoFar? }) => void for live status. */
  onProgress = null,
} = {}) {
  const results = [];
  const protectionWithheld = [];
  // topology + snapshot + stages + sweep (reported from finish via onProgress if needed)
  const stepTotal = 2 + stages.length + 1;
  let stepIndex = 0;
  const report = async (step, message, extra = {}) => {
    stepIndex += 1;
    if (typeof onProgress !== 'function') return;
    try {
      await onProgress({
        step,
        stepLabel: message,
        message,
        stepIndex,
        stepTotal,
        ...extra,
      });
    } catch { /* status must never abort the pipeline */ }
  };

  // ---- 1. topology -------------------------------------------------------
  let topology;
  try {
    ctx.audit.enterStage('topology');
    await report('topology', 'Checking repository topology…');
    topology = await checkTopology({
      rootPath: ctx.rootPath,
      git: ctx.git,
      fs: ctx.fs,
      reportDir: ctx.reportDir,
      isExcluded: (rel) => ctx.protection.isExcluded(rel),
    });
  } catch (err) {
    return finish(ctx, [failedStage('topology', err)], { startedAt, topology: null, snapshot: null, protectionWithheld });
  }
  ctx.state.topology = topology;

  if (topology.aborted) {
    // A junction escaping the root is not survivable read-only: we cannot know
    // what tree we are looking at, so we do not look.
    const aborted = failedStage('topology', new Error(topology.abortReason), { note: 'run aborted at the topology check' });
    return finish(ctx, [aborted], { startedAt, topology, snapshot: null, protectionWithheld });
  }
  results.push(makeStageResult({
    stage: 'topology',
    status: topology.status === 'partial' ? STATUS.PARTIAL : STATUS.OK,
    coverage: {
      scanned: (topology.inScope || []).length,
      skipped: 0,
      errored: (topology.errors || []).length,
      note: `${topology.excludedSubtrees.length} path(s) excluded by policy, ${topology.links.length} link object(s) recorded (never followed)`,
    },
    errors: (topology.errors || []).map((e) => ({ message: `${e.kind}: ${e.message}` })),
    notes: [
      ctx.git ? `repo toplevel=${topology.toplevel} (rootIsToplevel=${topology.rootIsToplevel})` : 'no repository — toplevel resolution not applicable',
    ],
  }));

  // ---- 2. snapshot S -----------------------------------------------------
  let snapshot = null;
  try {
    ctx.audit.enterStage('snapshot');
    await report('snapshot', 'Capturing filesystem snapshot…');
    snapshot = await captureSnapshot({
      rootPath: ctx.rootPath,
      head: ctx.git ? ctx.git.head : null,
      paths: topology.inScope || [],
      excluded: topology.excludedSubtrees,
      fs: ctx.fs,
      now: ctx.now,
    });
    ctx.state.snapshot = snapshot;
  } catch (err) {
    results.push(failedStage('snapshot', err));
    return finish(ctx, results, { startedAt, topology, snapshot: null, protectionWithheld });
  }

  // ---- 3+4. stages, each filtered through protection BEFORE emission -----
  for (const stage of stages) {
    let result;
    try {
      ctx.audit.enterStage(stage.name);
      await report(stage.name, `Running ${stage.name}…`, { stage: stage.name });
      result = await stage.run(ctx);
    } catch (err) {
      // A Tier-1 tripwire violation fails the RUN at the call site, naming the
      // offending stage and path — it is never downgraded to a stage warning.
      if (err instanceof WriteAuditViolation) {
        results.push(failedStage(stage.name, err, { note: 'ZERO-WRITE INVARIANT: the write was blocked before it happened' }));
        return finish(ctx, results, { startedAt, topology, snapshot, protectionWithheld });
      }
      results.push(failedStage(stage.name, err));
      continue;
    }

    const { kept, withheld } = ctx.protection.filter(result.findings);
    for (const w of withheld) protectionWithheld.push({ ...w, stage: stage.name });
    result.findings = kept;

    // Wave 2 honesty markers, applied AFTER protection so they only ever land on
    // findings that survived to be offered: the advisory marker names the apply
    // path and undo for a repo-less run, and the heuristic marker forces the
    // label + default-unchecked onto anything emitted in heuristic mode.
    markAdvisory(result.findings, ctx);
    markHeuristic(result.findings, ctx);

    // Content hashes enter S lazily, only for paths that became findings.
    for (const f of kept) {
      const rel = f.path;
      if (rel && snapshot.paths[rel]) {
        f.contentHash = await ensureHash(snapshot, rel, { fs: ctx.fs });
      }
    }

    results.push(result);
    const findingsSoFar = results.reduce((n, r) => n + ((r.findings || []).length), 0);
    if (typeof onProgress === 'function') {
      try {
        await onProgress({
          step: stage.name,
          stepLabel: `Finished ${stage.name}`,
          message: `Finished ${stage.name}` + (kept.length ? ` (${kept.length} finding(s) this stage)` : ''),
          stage: stage.name,
          findingsSoFar,
          stepIndex,
          stepTotal,
        });
      } catch { /* ignore */ }
    }
  }

  if (typeof onProgress === 'function') {
    try {
      await onProgress({
        step: 'sweep',
        stepLabel: 'Sweep / finalize',
        message: 'Checking for drift and assembling the envelope…',
        stepIndex: stepTotal,
        stepTotal,
        findingsSoFar: results.reduce((n, r) => n + ((r.findings || []).length), 0),
      });
    } catch { /* ignore */ }
  }

  return finish(ctx, results, { startedAt, topology, snapshot, protectionWithheld });
}

async function finish(ctx, results, { startedAt, topology, snapshot, protectionWithheld }) {
  let drift = [];
  let stale = [];

  if (snapshot) {
    const findingPaths = results.flatMap((r) => (r.findings || []).map((f) => f.path).filter(Boolean));
    let sweep;
    try {
      ctx.audit.enterStage('sweep');
      sweep = await sweepSnapshot(snapshot, { findingPaths, hermetic: ctx.hermetic, fs: ctx.fs });
    } catch (err) {
      results.push(failedStage('sweep', err));
      sweep = null;
    }
    if (sweep) {
      drift = sweep.drift;
      stale = sweep.stale;
      applyStaleness(results.flatMap((r) => r.findings || []), sweep.stale);
      results.push(makeStageResult({
        stage: 'sweep',
        status: sweep.status,
        coverage: {
          scanned: Object.keys(snapshot.paths).length,
          skipped: 0,
          errored: sweep.hermeticFailure ? sweep.deltas.length : 0,
          note: sweep.note,
        },
        errors: sweep.hermeticFailure
          ? sweep.deltas.map((d) => ({ message: `hermetic fixture: '${d.path}' ${d.kind} vs snapshot S — the engine wrote under the root` }))
          : [],
        notes: [sweep.note],
      }));
    }
  }

  // Wave 3 identity contract: ID = hash(run_id, action, path, content_hash),
  // generated HERE — at emission, after the lazy content hashes have landed and
  // after protection has filtered — so every finding a panel can render already
  // carries the only handle Apply will accept. A finding with no ID has no route
  // into the executor at all.
  stampFindingIds(results.flatMap((r) => r.findings || []), ctx.runId);

  // Tier 1: any recorded violation fails the run, even if a stage swallowed it.
  const tripwire = { violations: ctx.audit.violations, spawns: ctx.audit.spawns };
  if (tripwire.violations.length && !results.some((r) => r.status === STATUS.FAILED)) {
    const v = tripwire.violations[0];
    results.push(failedStage('tripwire', new Error(
      `ZERO-WRITE INVARIANT VIOLATED by stage '${v.stage}': ${v.op}() on '${v.target}'`)));
  }

  return makeRunEnvelope({
    runId: ctx.runId,
    rootPath: ctx.rootPath,
    mode: ctx.mode,
    ruleset: ctx.ruleset,
    reportDir: ctx.reportDir,
    git: ctx.git ? { toplevel: ctx.git.toplevel, head: ctx.git.head, branch: ctx.git.branch, rootIsToplevel: ctx.git.rootIsToplevel } : null,
    stages: results,
    snapshot,
    topology,
    protectionWithheld,
    exclusionLog: ctx.state.exclusionLog || [],
    secretGate: summariseSecretGate(ctx),
    dirty: summariseDirty(ctx),
    // Wave 5: identity is computed HERE, on every path, so the CLI launch, the
    // Anchor-dispatched launch and a bare library call all stamp the same
    // folder-derived answer into the envelope.
    identity: projectIdentity({
      rootPath: ctx.rootPath,
      git: ctx.git,
      gitSummary: ctx.state.gitSummary || null,
      anchor: ctx.launch && ctx.launch.anchor ? ctx.launch.anchor : null,
    }),
    costGate: ctx.costGate || null,
    verdictCache: ctx.verdictCache && typeof ctx.verdictCache.summary === 'function' ? ctx.verdictCache.summary() : null,
    preflight: preflightRecord(results),
    drift,
    stale,
    tripwire,
    startedAt,
    endedAt: new Date().toISOString(),
  });
}

/** What the universal pre-LLM gate did this run, in one place a renderer can read. */
function summariseSecretGate(ctx) {
  const verdicts = ctx.state.triage;
  if (!verdicts) return null;
  const blocked = [...(ctx.state.llmBlocked || [])];
  return {
    ran: true,
    scanned: verdicts.size,
    blocked,
    blockedCount: blocked.length,
    quarantined: ctx.state.quarantined || [],
    scanExemptFromReadCap: true,
    note: 'the gate ran over every in-scope path (content AND path/filename), streaming and full-file including binaries and files past the LLM read cap, BEFORE any stage sent content to a model',
  };
}

/**
 * The dirty-tree policy, encoded: the count is RECORDED and the scan is never
 * blocked. `blockedScan: false` is stated rather than implied so a reader can
 * see that no version of this tool refused a dirty tree.
 */
function summariseDirty(ctx) {
  const p = ctx.state.porcelain;
  if (!ctx.git) return { present: false, reason: 'no repository — dirtiness is not a concept here' };
  const summary = ctx.state.gitSummary || null;
  return {
    present: true,
    count: p ? p.dirtyCount() : (summary ? summary.dirtyCount : null),
    dirty: p ? p.dirtyCount() > 0 : Boolean(summary && summary.dirty),
    blockedScan: false,
    note: 'a dirty working tree never blocks a scan; it is recorded so the panel can explain per-file Apply gating, and dirty tracked paths are hard-excluded from REMOVE (see exclusionLog)',
  };
}

function preflightRecord(results) {
  const stage = (results || []).find((r) => r.stage === 'preflight');
  return stage && stage.data ? stage.data : null;
}

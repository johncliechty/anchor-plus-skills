// engine/envelope.mjs — Wave 1: the typed stage-result and run envelope.
//
// One contract, consumed by the orchestrator now and by the Wave-6 renderer
// later. The two properties that matter:
//
//   TERMINAL STATE = WORST STAGE STATUS. A run is exactly as healthy as its
//     unhealthiest stage. There is no averaging and no "mostly fine".
//
//   CELEBRATORY-CLEAN IS STRUCTURALLY UNREACHABLE. `isClean` is a computed
//     property that requires EVERY stage to be status=ok with COMPLETE coverage
//     (nothing skipped, nothing errored) and zero findings. There is no
//     findings-count path to a clean verdict, so a run that failed to look at
//     half the tree can never render as clean — it renders as what it is.

export const STATUS = Object.freeze({ OK: 'ok', PARTIAL: 'partial', FAILED: 'failed' });

const RANK = { ok: 0, partial: 1, failed: 2 };

/** The worst (highest-rank) status in a list; 'ok' for an empty list. */
export function worstStatus(statuses) {
  let worst = STATUS.OK;
  for (const s of statuses || []) {
    const v = RANK[s];
    if (v === undefined) throw new Error(`unknown stage status '${s}' — the envelope contract admits only ok|partial|failed`);
    if (v > RANK[worst]) worst = s;
  }
  return worst;
}

/** Coverage is complete only when nothing was skipped and nothing errored. */
export function coverageComplete(coverage) {
  if (!coverage) return false;
  return Number(coverage.skipped || 0) === 0 && Number(coverage.errored || 0) === 0;
}

/**
 * Build a stage result envelope. Every stage returns exactly this shape.
 *
 * @param {{stage: string, status?: string, coverage?: object, findings?: object[], errors?: object[], notes?: string[], data?: object}} parts
 */
export function makeStageResult({ stage, status = STATUS.OK, coverage = {}, findings = [], errors = [], notes = [], data = null } = {}) {
  if (!stage) throw new Error('a stage result must name its stage');
  if (!(status in RANK)) throw new Error(`stage '${stage}' returned unknown status '${status}'`);
  const cov = {
    scanned: Number(coverage.scanned || 0),
    skipped: Number(coverage.skipped || 0),
    errored: Number(coverage.errored || 0),
    ...(coverage.note ? { note: coverage.note } : {}),
  };
  // An errored stage that still claims 'ok' is the fake-clean failure mode in
  // miniature — the contract will not accept it.
  if (status === STATUS.OK && (errors || []).length > 0) {
    throw new Error(`stage '${stage}' reported status=ok while carrying ${errors.length} error(s) — a stage with errors is partial or failed, never ok`);
  }
  return {
    stage,
    status,
    coverage: cov,
    findings: [...findings],
    errors: [...errors],
    notes: [...notes],
    ...(data ? { data } : {}),
  };
}

/** A stage that could not run at all. */
export function failedStage(stage, error, extra = {}) {
  return makeStageResult({
    stage,
    status: STATUS.FAILED,
    coverage: { scanned: 0, skipped: 0, errored: 1, note: extra.note || 'stage did not run' },
    errors: [{ message: error && error.message ? error.message : String(error), name: (error && error.name) || 'Error', ...(extra.detail ? { detail: extra.detail } : {}) }],
  });
}

/**
 * Compose the run envelope from stage results. `isClean` is computed here and
 * nowhere else.
 */
export function makeRunEnvelope({
  runId,
  rootPath,
  mode,
  ruleset,
  reportDir,
  git = null,
  stages = [],
  snapshot = null,
  topology = null,
  protectionWithheld = [],
  drift = [],
  stale = [],
  tripwire = { violations: [], spawns: [] },
  // Wave 2 additions. All default to empty so a Wave-1 caller composes the same
  // envelope it always did.
  exclusionLog = [],
  secretGate = null,
  dirty = null,
  preflight = null,
  // Wave 5 additions. All default to null so a Wave-1..4 caller composes exactly
  // the envelope it always did.
  identity = null,
  costGate = null,
  verdictCache = null,
  startedAt = null,
  endedAt = null,
} = {}) {
  const status = worstStatus(stages.map((s) => s.status));
  const findings = stages.flatMap((s) => s.findings || []);
  const errors = stages.flatMap((s) => (s.errors || []).map((e) => ({ stage: s.stage, ...e })));
  const allOk = stages.length > 0 && stages.every((s) => s.status === STATUS.OK);
  const allCovered = stages.length > 0 && stages.every((s) => coverageComplete(s.coverage));
  const noViolations = !(tripwire && tripwire.violations && tripwire.violations.length);

  const isClean = Boolean(allOk && allCovered && noViolations && findings.length === 0);

  const cleanBlockers = [];
  if (!stages.length) cleanBlockers.push('no stages ran');
  if (!allOk) cleanBlockers.push(`stage(s) not ok: ${stages.filter((s) => s.status !== STATUS.OK).map((s) => `${s.stage}=${s.status}`).join(', ')}`);
  if (!allCovered) cleanBlockers.push(`incomplete coverage: ${stages.filter((s) => !coverageComplete(s.coverage)).map((s) => `${s.stage}(skipped=${s.coverage.skipped},errored=${s.coverage.errored})`).join(', ')}`);
  if (!noViolations) cleanBlockers.push('zero-write tripwire violation(s) recorded');
  if (findings.length) cleanBlockers.push(`${findings.length} finding(s)`);

  return {
    envelopeVersion: 1,
    runId,
    rootPath,
    mode,
    ruleset,
    reportDir,
    /**
     * Wave 5: WHICH project this is, derived from the folder itself (name +
     * absolute path + git status) and never from an Anchor registry — so the
     * panel header reads identically on a plain folder and an Anchor project.
     */
    identity,
    /** The pre-scan cost gate's verbatim record. `blocked` there is always false. */
    costGate,
    /** What the content-hash verdict cache did this run. */
    verdictCache,
    git: git ? { present: true, ...git } : { present: false },
    startedAt,
    endedAt,
    status,
    isClean,
    cleanBlockers,
    stages,
    findings,
    errors,
    snapshot,
    topology,
    protectionWithheld,
    /**
     * Removal-eligibility exclusions, each with git's verbatim porcelain line.
     * "The tool never considered this file" and "the tool considered it and git
     * said it was dirty" are different claims; this is how the panel proves
     * which one happened.
     */
    exclusionLog,
    /** What the universal pre-LLM secret gate blocked, and how much it read. */
    secretGate,
    /** Dirty-tree policy: recorded, NEVER a reason to refuse the scan. */
    dirty,
    /** Non-git preflight result — a proposal record, never an action. */
    preflight,
    drift,
    stale,
    tripwire: {
      // Canonical names, matching the orchestrator's in-flight tripwire object
      // ({violations, spawns}) so a consumer reads the same key end to end.
      violations: (tripwire && tripwire.violations) || [],
      spawns: (tripwire && tripwire.spawns) || [],
      // Back-compat aliases (the Wave-6 banners and the engine-tripwire tests
      // read these); kept so renaming here breaks no existing reader.
      tier1Violations: (tripwire && tripwire.violations) || [],
      spawnLog: (tripwire && tripwire.spawns) || [],
    },
  };
}

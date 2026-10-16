// src/telemetry.mjs — Wave 11: day-one per-run telemetry.
//
// The plan deferred several open questions ("how often do users EDIT?", "how often
// does an EDIT re-derive fail to ABORT?", "do runs restart after an ABORT?", "which
// intake route do real runs take?", "how often does the budget gate fire?") to be
// answered by MEASUREMENT rather than argument. This module turns each Stage-0 run
// result (src/stage0-plan.mjs) into one structured, deterministic telemetry record
// so those questions become measured decisions:
//
//   - EDIT-round count per run;
//   - EDIT re-derive parse-FAIL -> ABORT frequency (the stamped rederive abort);
//   - ABORT-restart frequency (a run recorded after a prior run ABORTed);
//   - path taken: content / intent-only / seeds-only-bootstrap / zero-input-fail-fast;
//   - seeds: present, passed strict validation, rejected, and fed to derive;
//   - verbatim-anchor-check failures surfaced in the advisory sidecar;
//   - over-budget fail-fast vs auto-truncate events.
//
// The module is PURE and deterministic: no clock, no randomness, no I/O, no mutation
// of its inputs (mirroring src/posture-resolver.mjs and the timestamp-free
// src/pipeline-state.mjs convention — the same run content always emits the same
// record bytes). Every record is validated by assertTelemetryRecord and deep-frozen
// before it is returned, so a collector bug can never emit a partial record.

/** Version stamp carried by every telemetry record. */
export const TELEMETRY_VERSION = 'litreview-telemetry/1';

/**
 * The shared re-derive abort stamp (trio-shared/brownfield-intake/rederiveFromProse.mjs
 * REDERIVE_ABORT_STAMP). Duplicated as a literal because this module is synchronous
 * and pure while the shared module resolves through the async trio pin; the parity is
 * pinned by test/telemetry.test.mjs against the shared module's own export.
 */
export const REDERIVE_ABORT_STAMP = 'brownfield-intake/rederive-abort/1';

/**
 * The four run paths, verbatim the shared module's INTAKE_ROUTES tokens
 * (trio-shared/brownfield-intake/index.mjs) — telemetry invents no second naming.
 */
export const RUN_PATHS = Object.freeze([
  'content',
  'intent-only',
  'seeds-only-bootstrap',
  'zero-input-fail-fast',
]);

/** Required sub-fields of the per-run `seeds` block. */
export const TELEMETRY_SEED_FIELDS = Object.freeze([
  'present',
  'passedValidation',
  'rejected',
  'fedToDerive',
]);

/** Required sub-fields of the per-run `budget` block. */
export const TELEMETRY_BUDGET_FIELDS = Object.freeze(['overBudgetFailFast', 'autoTruncated']);

/** Every field a per-run telemetry record MUST emit, for every run path. */
export const TELEMETRY_FIELDS = Object.freeze([
  'telemetryVersion',
  'runPath',
  'status',
  'editRounds',
  'rederiveParseCalls',
  'rederiveParseFailAbort',
  'abortRestart',
  'seeds',
  'anchorCheckFailures',
  'budget',
]);

export class TelemetryError extends Error {
  constructor(message) {
    super(message);
    this.name = 'TelemetryError';
  }
}

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const v of Object.values(value)) deepFreeze(v);
    Object.freeze(value);
  }
  return value;
}

/**
 * A verbatim-anchor-check failure is distinguishable from a schema/binding reason by
 * shape, not by parsing prose: the deterministic anchor check
 * (trio-shared/brownfield-intake/verbatimAnchorCheck.mjs) emits
 * `{ path, sourceId, quote, reason }` entries — schema reasons carry no
 * sourceId/quote keys. These are the failures the advisory readiness sidecar
 * (planReadinessPreview) surfaces per element.
 */
function isAnchorCheckFailure(failure) {
  return (
    failure !== null &&
    typeof failure === 'object' &&
    !Array.isArray(failure) &&
    (Object.prototype.hasOwnProperty.call(failure, 'quote') ||
      Object.prototype.hasOwnProperty.call(failure, 'sourceId'))
  );
}

/**
 * Build the ONE telemetry record for a Stage-0 run result. Total over every run path:
 * RUN, HALTED, ABORTED (gate abort AND stamped re-derive abort), and FAILED
 * (zero-input fail-fast, budget fail-fast, derive failure) all emit every field.
 *
 * @param {object} options
 * @param {object} options.stage0 A runStage0Plan result (src/stage0-plan.mjs) — any
 *   status. Fresh-intake runs carry `intake` (the shared BrownfieldIntakeResult);
 *   resumed runs derive seed counts from the serialized artifact instead.
 * @param {boolean} [options.restartAfterAbort] True when this run follows a prior
 *   ABORTED run (the ABORT-restart signal; createTelemetrySession derives it).
 * @returns {Readonly<object>} deep-frozen, assertTelemetryRecord-validated record
 */
export function buildRunTelemetry({ stage0, restartAfterAbort = false } = {}) {
  if (stage0 === null || typeof stage0 !== 'object' || Array.isArray(stage0)) {
    throw new TelemetryError('buildRunTelemetry: stage0 must be a runStage0Plan result object');
  }
  if (typeof stage0.status !== 'string' || stage0.status === '') {
    throw new TelemetryError('buildRunTelemetry: stage0 result carries no status');
  }

  // ── EDIT rounds: presentations are captured once per gate presentation, so N
  //    presentations = N-1 accepted EDIT rounds. Headless approvalProvider runs
  //    capture no presentations; there the approved path is the honest signal
  //    (approve-with-edits implies exactly one bounded EDIT round, the gate's max). ──
  const presentations = Array.isArray(stage0.presentations) ? stage0.presentations.length : 0;
  const approvedPath = stage0.decision?.path ?? stage0.state?.plan?.approvedPath ?? null;
  const editRounds =
    presentations > 0 ? presentations - 1 : approvedPath === 'approve-with-edits' ? 1 : 0;

  // ── The stamped re-derive fail-to-ABORT (parse-FAIL, schema-FAIL, anchor-FAIL,
  //    binding-FAIL) vs a plain gate ABORT: only the former carries the shared
  //    rederive stamp — on the result's abort record or the serialized state's. ──
  const abortRecord = stage0.abort ?? stage0.state?.abort ?? null;
  const rederiveParseFailAbort =
    stage0.status === 'ABORTED' && abortRecord?.stamp === REDERIVE_ABORT_STAMP;
  const rederiveParseCalls = stage0.decision?.parseCalls ?? 0;

  // ── Seeds: fresh-intake runs count from the shared module's strict validation
  //    split; resumed runs (zero intake calls) count from the serialized artifact,
  //    whose seed set upstream validation + Wave-8 reconciliation already pinned. ──
  const intakeSeeds = stage0.intake?.seeds ?? null;
  const artifactSeedCount = Array.isArray(stage0.artifact?.seeds) ? stage0.artifact.seeds.length : 0;
  const accepted = Array.isArray(intakeSeeds?.accepted) ? intakeSeeds.accepted.length : 0;
  const rejected = Array.isArray(intakeSeeds?.rejected) ? intakeSeeds.rejected.length : 0;
  const deriveCalls = stage0.intake?.deriveCalls ?? 0;
  // The seeds-only bootstrap consumes seeds deterministically (zero derive calls),
  // so its accepted seeds count as fed; a pre-derive failure (fail-fast, zero-input)
  // fed nothing.
  const seeds = intakeSeeds
    ? {
        present: accepted + rejected,
        passedValidation: accepted,
        rejected,
        fedToDerive: deriveCalls > 0 || stage0.route === 'seeds-only-bootstrap' ? accepted : 0,
      }
    : {
        present: artifactSeedCount,
        passedValidation: artifactSeedCount,
        rejected: 0,
        fedToDerive: artifactSeedCount,
      };

  // ── Anchor-check failures surfaced in the advisory sidecar: derive-time failures
  //    ride the intake failure record (planReadinessPreview surfaces them); re-derive
  //    failures ride the stamped abort record. Counted by shape, never by prose. ──
  const surfacedFailures = [
    ...(Array.isArray(stage0.intake?.failure?.failures) ? stage0.intake.failure.failures : []),
    ...(Array.isArray(abortRecord?.failures) ? abortRecord.failures : []),
  ];
  const anchorCheckFailures = surfacedFailures.filter(isAnchorCheckFailure).length;

  // ── Budget events: the Wave-6 door decision ('fail-fast' stops before Gandalf;
  //    an explicit auto-truncate proceeds STAMPED — the stamp also survives resume
  //    through the serialized pipeline state). ──
  const budget = {
    overBudgetFailFast: stage0.intake?.ingest?.decision === 'fail-fast',
    autoTruncated: stage0.intake?.truncated === true || stage0.state?.truncated === true,
  };

  const record = {
    telemetryVersion: TELEMETRY_VERSION,
    runPath: typeof stage0.route === 'string' ? stage0.route : null,
    status: stage0.status,
    editRounds,
    rederiveParseCalls,
    rederiveParseFailAbort,
    abortRestart: restartAfterAbort === true,
    seeds,
    anchorCheckFailures,
    budget,
  };
  assertTelemetryRecord(record);
  return deepFreeze(record);
}

/**
 * The CI-enforceable record invariant: throws TelemetryError (naming the omission)
 * unless every TELEMETRY_FIELDS entry — and every seeds/budget sub-field — is
 * present with its expected type. This is what "every listed field is emitted for
 * each run path" means in code.
 * @returns {true}
 */
export function assertTelemetryRecord(record) {
  if (record === null || typeof record !== 'object' || Array.isArray(record)) {
    throw new TelemetryError('telemetry record must be an object');
  }
  for (const field of TELEMETRY_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, field)) {
      throw new TelemetryError(`telemetry record is missing required field "${field}"`);
    }
  }
  if (record.telemetryVersion !== TELEMETRY_VERSION) {
    throw new TelemetryError(
      `telemetry record carries version ${JSON.stringify(record.telemetryVersion)}, expected ${TELEMETRY_VERSION}`,
    );
  }
  if (record.runPath !== null && !RUN_PATHS.includes(record.runPath)) {
    throw new TelemetryError(
      `telemetry runPath ${JSON.stringify(record.runPath)} is not one of ${RUN_PATHS.join(' | ')} (or null)`,
    );
  }
  if (typeof record.status !== 'string' || record.status === '') {
    throw new TelemetryError('telemetry status must be a non-empty string');
  }
  for (const numeric of ['editRounds', 'rederiveParseCalls', 'anchorCheckFailures']) {
    if (!Number.isInteger(record[numeric]) || record[numeric] < 0) {
      throw new TelemetryError(`telemetry ${numeric} must be a non-negative integer`);
    }
  }
  for (const bool of ['rederiveParseFailAbort', 'abortRestart']) {
    if (typeof record[bool] !== 'boolean') {
      throw new TelemetryError(`telemetry ${bool} must be a boolean`);
    }
  }
  for (const [block, fields] of [
    ['seeds', TELEMETRY_SEED_FIELDS],
    ['budget', TELEMETRY_BUDGET_FIELDS],
  ]) {
    const value = record[block];
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      throw new TelemetryError(`telemetry ${block} must be an object`);
    }
    for (const field of fields) {
      if (!Object.prototype.hasOwnProperty.call(value, field)) {
        throw new TelemetryError(`telemetry ${block} is missing required field "${field}"`);
      }
    }
  }
  for (const seedField of TELEMETRY_SEED_FIELDS) {
    if (!Number.isInteger(record.seeds[seedField]) || record.seeds[seedField] < 0) {
      throw new TelemetryError(`telemetry seeds.${seedField} must be a non-negative integer`);
    }
  }
  for (const budgetField of TELEMETRY_BUDGET_FIELDS) {
    if (typeof record.budget[budgetField] !== 'boolean') {
      throw new TelemetryError(`telemetry budget.${budgetField} must be a boolean`);
    }
  }
  return true;
}

/**
 * A session accumulator over consecutive runs: derives the ABORT-restart signal (a
 * run recorded after a prior ABORTED run) and aggregates the day-one frequencies the
 * deferred open questions need. Order of recordRun calls IS the run order.
 *
 * @returns {{
 *   recordRun: (stage0: object) => Readonly<object>,
 *   records: () => ReadonlyArray<object>,
 *   summary: () => Readonly<object>,
 * }}
 */
export function createTelemetrySession() {
  const records = [];
  let previousStatus = null;
  return {
    recordRun(stage0) {
      const record = buildRunTelemetry({ stage0, restartAfterAbort: previousStatus === 'ABORTED' });
      previousStatus = record.status;
      records.push(record);
      return record;
    },
    records() {
      return Object.freeze([...records]);
    },
    summary() {
      const byPath = {};
      for (const pathName of RUN_PATHS) byPath[pathName] = 0;
      let unroutedRuns = 0;
      let editRounds = 0;
      let rederiveParseFailAborts = 0;
      let abortRestarts = 0;
      let anchorCheckFailures = 0;
      let overBudgetFailFasts = 0;
      let autoTruncations = 0;
      for (const record of records) {
        if (record.runPath === null) unroutedRuns += 1;
        else byPath[record.runPath] += 1;
        editRounds += record.editRounds;
        if (record.rederiveParseFailAbort) rederiveParseFailAborts += 1;
        if (record.abortRestart) abortRestarts += 1;
        anchorCheckFailures += record.anchorCheckFailures;
        if (record.budget.overBudgetFailFast) overBudgetFailFasts += 1;
        if (record.budget.autoTruncated) autoTruncations += 1;
      }
      return deepFreeze({
        telemetryVersion: TELEMETRY_VERSION,
        totalRuns: records.length,
        byPath,
        unroutedRuns,
        editRounds,
        rederiveParseFailAborts,
        abortRestarts,
        anchorCheckFailures,
        overBudgetFailFasts,
        autoTruncations,
      });
    },
  };
}

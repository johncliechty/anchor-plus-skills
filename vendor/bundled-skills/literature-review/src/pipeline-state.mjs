// src/pipeline-state.mjs — Wave 9: full pipeline-state serialization at the Stage-0
// HALT boundary.
//
// Stage-0 is a TRUE stage, not a mid-pipeline interrupt: it fully initializes PRISMA
// state before the run halts at the frozen plan-review gate, and the ENTIRE pipeline
// state (plan artifact + rendered plan body + grounding cache + PRISMA counts) is
// serialized here so a halted run resumes exactly where it stopped — with ZERO extra
// LLM calls and PRISMA counts / grounding cache BYTE-identical to a no-HALT run of
// the same approved plan.
//
// Serialization is canonical and deterministic: keys are sorted recursively, the
// state carries NO timestamps or other run-varying fields, so the same content
// serializes to the same bytes regardless of construction order or halt/resume
// history (what test/stage0-resume-invariance.test.mjs pins). All mutators return a
// NEW state object; nothing here mutates in place.

import fs from 'node:fs';

export const PIPELINE_STATE_VERSION = 'litreview-pipeline-state/1';

/** Pipeline stage markers carried by the serialized state. */
export const PIPELINE_STAGES = Object.freeze({
  STAGE0_PLAN: 'stage0-plan',
  SNOWBALL: 'snowball',
});

/** Stage-0 plan statuses the serialized state can carry. */
export const PIPELINE_STATUSES = Object.freeze({
  HALTED: 'HALTED',
  APPROVED: 'APPROVED',
  ABORTED: 'ABORTED',
});

/**
 * The fully-initialized (but NOT advanced) PRISMA state Stage-0 owns: every counter
 * present and zero, the exclusion log present and empty. Snowball ADVANCES this via
 * advancePrismaWithSnowball; Stage-0 never does.
 *
 * @returns {{ identified: number, screened: number, included: number,
 *   excluded: number, exclusions: object[] }}
 */
export function initialPrismaState() {
  return { identified: 0, screened: 0, included: 0, excluded: 0, exclusions: [] };
}

/** Recursive sorted-key clone: the canonical-serialization core (arrays keep order). */
function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeysDeep(value[key]);
    return out;
  }
  return value;
}

/**
 * Initialize the full pipeline state at the Stage-0 HALT boundary.
 *
 * @param {object} options
 * @param {import('<path>').PlanArtifact}
 *   options.artifact The derived PlanArtifact (the shared module's end-to-end output).
 * @param {string} options.planBody The rendered prose plan body presented at the gate.
 * @param {string|null} [options.coverageSidecar] The advisory coverage sidecar (display only).
 * @param {Record<string,string>} [options.groundedSources] sourceId -> grounded text —
 *   the grounding cache the gate round-trip (and any resume) consumes.
 * @param {'content'|'intent-only'|'seeds-only-bootstrap'} [options.route] Intake route taken.
 * @param {boolean} [options.truncated] Intake auto-truncation posture flag.
 * @param {object|null} [options.truncationStamp] The TRUNCATED stamp when truncated.
 * @returns {object} the new pipeline state (status HALTED, PRISMA initialized, not advanced)
 */
export function initializePipelineState({
  artifact,
  planBody,
  coverageSidecar = null,
  groundedSources = {},
  route = null,
  truncated = false,
  truncationStamp = null,
} = {}) {
  if (artifact === null || typeof artifact !== 'object') {
    throw new TypeError('initializePipelineState: artifact must be the derived PlanArtifact object');
  }
  if (typeof planBody !== 'string') {
    throw new TypeError('initializePipelineState: planBody must be the rendered prose plan body string');
  }
  return {
    stateVersion: PIPELINE_STATE_VERSION,
    stage: PIPELINE_STAGES.STAGE0_PLAN,
    status: PIPELINE_STATUSES.HALTED,
    route,
    plan: {
      artifact,
      planBody,
      coverageSidecar,
      planHash: null,
      approvedPath: null,
    },
    prisma: initialPrismaState(),
    // Sorted at construction so the in-memory cache carries the same key order a
    // resumed run reads back from the canonical serialization (byte-invariance).
    groundingCache: { sources: sortKeysDeep({ ...groundedSources }) },
    truncated,
    truncationStamp,
    abort: null,
  };
}

/**
 * Mark the plan APPROVED (gate resolved, execution artifact bound). Returns a new state.
 *
 * @param {object} state
 * @param {{ planHash: string, approvedPath: 'approve-verbatim'|'approve-with-edits' }} outcome
 */
export function markPlanApproved(state, { planHash, approvedPath }) {
  return {
    ...state,
    status: PIPELINE_STATUSES.APPROVED,
    plan: { ...state.plan, planHash, approvedPath },
  };
}

/**
 * Mark the plan ABORTED (gate ABORT, or the bounded re-derive fail-to-ABORT) with its
 * stamped reason. Returns a new state; an aborted state never reaches snowball.
 *
 * @param {object} state
 * @param {{ stamp: string, reason: string, failures?: object[] }} abort
 */
export function markPlanAborted(state, { stamp, reason, failures = [] }) {
  return {
    ...state,
    status: PIPELINE_STATUSES.ABORTED,
    abort: { stamp, reason, failures },
  };
}

/**
 * Advance the initialized PRISMA state with the snowball result — the ONLY place
 * PRISMA counts move. Deterministic: a pure function of the search result, so a
 * halted-then-resumed run and a no-HALT run of the same approved plan advance to
 * byte-identical PRISMA state.
 *
 * @param {object} state A state whose plan is APPROVED.
 * @param {{ candidates: object[], prismaExclusions: { exclusions: object[] } }} search
 *   The performSnowballSearch result (candidates already deterministically ranked).
 * @returns {object} new state at the snowball stage with PRISMA counts advanced
 */
export function advancePrismaWithSnowball(state, { candidates, prismaExclusions }) {
  if (state?.status !== PIPELINE_STATUSES.APPROVED) {
    throw new Error('advancePrismaWithSnowball: PRISMA advances only after the plan is APPROVED');
  }
  const included = Array.isArray(candidates) ? candidates.length : 0;
  const exclusions = Array.isArray(prismaExclusions?.exclusions) ? prismaExclusions.exclusions : [];
  return {
    ...state,
    stage: PIPELINE_STAGES.SNOWBALL,
    prisma: {
      identified: included + exclusions.length,
      screened: included + exclusions.length,
      included,
      excluded: exclusions.length,
      exclusions: exclusions.map((e) => ({
        paperId: e.paperId ?? null,
        title: e.title ?? null,
        reason: e.reason ?? null,
        details: e.details ?? '',
      })),
    },
  };
}

/**
 * Canonical byte-stable serialization: recursively sorted keys, 2-space indent, one
 * trailing newline. Same content -> same bytes, always.
 *
 * @param {object} state
 * @returns {string}
 */
export function serializePipelineState(state) {
  return JSON.stringify(sortKeysDeep(state), null, 2) + '\n';
}

/**
 * Durably write the serialized pipeline state (the HALT boundary write).
 *
 * @param {string} filePath
 * @param {object} state
 * @returns {string} the serialized bytes written
 */
export function writePipelineState(filePath, state) {
  const serialized = serializePipelineState(state);
  fs.writeFileSync(filePath, serialized, 'utf8');
  return serialized;
}

/**
 * Read a previously-serialized pipeline state; null when absent. A file that exists
 * but is not a recognizable pipeline state throws (a corrupt halt boundary must
 * never be silently ignored into a fresh run).
 *
 * @param {string} filePath
 * @returns {object|null}
 */
export function readPipelineState(filePath) {
  if (!fs.existsSync(filePath)) return null;
  const raw = fs.readFileSync(filePath, 'utf8');
  let state;
  try {
    state = JSON.parse(raw);
  } catch (err) {
    throw new Error(`readPipelineState: ${filePath} is not valid JSON: ${err.message}`);
  }
  if (state?.stateVersion !== PIPELINE_STATE_VERSION) {
    throw new Error(
      `readPipelineState: ${filePath} carries stateVersion ${JSON.stringify(state?.stateVersion)}, ` +
        `expected ${PIPELINE_STATE_VERSION}`,
    );
  }
  return state;
}

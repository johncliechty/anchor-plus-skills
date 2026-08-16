/**
 * Wave 5 — Decision record: step-type → skill → confirmation map.
 *
 * RESEARCH → researchPrime
 * PLAN     → Crucible
 * BUILD    → Foreman
 * REVIEW   → Gandalf (dispatch entry only)
 *
 * CONFIRM-TO-PLAN binds a step ULID.
 * CONFIRM-TO-BUILD binds an approved plan artifact VERSION.
 * Auto-flow (PLAN handback → BUILD without confirm) is refused by test.
 */

export const STEP_TYPE_MAP_SCHEMA = 'ecgberht-step-type-map-v0';

export const STEP_TYPES = Object.freeze([
  'RESEARCH',
  'PLAN',
  'BUILD',
  'REVIEW',
]);

/** Locked map later waves import. */
export const STEP_TYPE_SKILL_MAP = Object.freeze({
  RESEARCH: {
    skill: 'researchPrime',
    confirmation: null,
    note: 'research commission; no plan/build confirm binding',
  },
  PLAN: {
    skill: 'Crucible',
    confirmation: 'CONFIRM-TO-PLAN',
    binds: 'step_ulid',
    note: 'CONFIRM-TO-PLAN binds a step ULID before PLAN spend',
  },
  BUILD: {
    skill: 'Foreman',
    confirmation: 'CONFIRM-TO-BUILD',
    binds: 'plan_artifact_version',
    note: 'CONFIRM-TO-BUILD binds an approved plan artifact VERSION',
  },
  REVIEW: {
    skill: 'Gandalf',
    confirmation: null,
    dispatch_entry_only: true,
    note: 'REVIEW → Gandalf dispatch entry only (no auto-chain into plan/build)',
  },
});

/**
 * @returns {object} machine-readable decision record
 */
export function stepTypeMapRecord() {
  return {
    schema: STEP_TYPE_MAP_SCHEMA,
    step_types: [...STEP_TYPES],
    map: { ...STEP_TYPE_SKILL_MAP },
    confirmations: {
      'CONFIRM-TO-PLAN': {
        binds: 'step_ulid',
        required_before: 'PLAN',
        skill: 'Crucible',
      },
      'CONFIRM-TO-BUILD': {
        binds: 'plan_artifact_version',
        required_before: 'BUILD',
        skill: 'Foreman',
      },
    },
    auto_flow: false,
    auto_flow_rule:
      'An approved plan artifact returned as a PLAN handback never starts BUILD automatically; CONFIRM-TO-BUILD bound to that artifact VERSION is required.',
  };
}

/**
 * Resolve skill for a step type.
 * @param {string} stepType
 * @returns {{ ok: true, skill: string, entry: object } | { ok: false, code: string, message: string }}
 */
export function skillForStepType(stepType) {
  const key = String(stepType || '')
    .trim()
    .toUpperCase();
  const entry = STEP_TYPE_SKILL_MAP[key];
  if (!entry) {
    return {
      ok: false,
      code: 'unknown-step-type',
      message: `Step type must be one of: ${STEP_TYPES.join(', ')}`,
    };
  }
  return { ok: true, skill: entry.skill, entry, step_type: key };
}

/**
 * Build a CONFIRM-TO-PLAN binding (step ULID required).
 * @param {{ step_ulid: string, who?: object|string, at?: string }} opts
 */
export function confirmToPlan(opts = {}) {
  const step_ulid = opts.step_ulid == null ? '' : String(opts.step_ulid).trim();
  if (!step_ulid) {
    return {
      ok: false,
      code: 'confirm-to-plan-requires-step-ulid',
      message: 'CONFIRM-TO-PLAN binds a step ULID — none supplied.',
    };
  }
  return {
    ok: true,
    confirmation: {
      kind: 'CONFIRM-TO-PLAN',
      binds: 'step_ulid',
      step_ulid,
      skill: 'Crucible',
      step_type: 'PLAN',
      at: opts.at ?? new Date().toISOString(),
      who: opts.who ?? null,
    },
  };
}

/**
 * Build a CONFIRM-TO-BUILD binding (approved plan artifact VERSION required).
 * @param {{ plan_artifact_version: string, plan_artifact_id?: string, who?: object|string, at?: string }} opts
 */
export function confirmToBuild(opts = {}) {
  const plan_artifact_version =
    opts.plan_artifact_version == null
      ? ''
      : String(opts.plan_artifact_version).trim();
  if (!plan_artifact_version) {
    return {
      ok: false,
      code: 'confirm-to-build-requires-version',
      message:
        'CONFIRM-TO-BUILD binds an approved plan artifact VERSION — none supplied.',
    };
  }
  return {
    ok: true,
    confirmation: {
      kind: 'CONFIRM-TO-BUILD',
      binds: 'plan_artifact_version',
      plan_artifact_version,
      plan_artifact_id: opts.plan_artifact_id ?? null,
      skill: 'Foreman',
      step_type: 'BUILD',
      at: opts.at ?? new Date().toISOString(),
      who: opts.who ?? null,
    },
  };
}

/**
 * Lifecycle attempt to flow a PLAN handback onward.
 * Auto-flow is ALWAYS refused — CONFIRM-TO-BUILD is required.
 *
 * @param {{
 *   step_type?: string,
 *   skill?: string,
 *   kind?: string,
 *   artifact_version?: string,
 *   plan_artifact_version?: string,
 *   handback_kind?: string,
 * }} planHandback
 * @param {{ confirm_to_build?: object|null }} [opts]
 * @returns {object}
 */
export function attemptPlanToBuildFlow(planHandback = {}, opts = {}) {
  const stepType = String(
    planHandback.step_type || planHandback.handback_kind || '',
  )
    .trim()
    .toUpperCase();
  const skill = planHandback.skill || '';
  const isPlan =
    stepType === 'PLAN' ||
    skill === 'Crucible' ||
    planHandback.kind === 'plan_handback' ||
    planHandback.approved_plan === true;

  if (!isPlan) {
    return {
      ok: false,
      code: 'not-a-plan-handback',
      message: 'Lifecycle flow expects an approved PLAN handback.',
      auto_flow: false,
      build_started: false,
    };
  }

  const version =
    planHandback.plan_artifact_version ??
    planHandback.artifact_version ??
    null;

  const confirm = opts.confirm_to_build ?? null;
  if (
    !confirm ||
    confirm.kind !== 'CONFIRM-TO-BUILD' ||
    !confirm.plan_artifact_version
  ) {
    return {
      ok: false,
      code: 'confirm-to-build-required',
      message:
        'No BUILD starts automatically from a PLAN handback; CONFIRM-TO-BUILD bound to the artifact VERSION is required.',
      auto_flow: false,
      build_started: false,
      requires: 'CONFIRM-TO-BUILD',
      plan_artifact_version: version,
    };
  }

  if (
    version != null &&
    String(confirm.plan_artifact_version) !== String(version)
  ) {
    return {
      ok: false,
      code: 'confirm-to-build-version-mismatch',
      message:
        'CONFIRM-TO-BUILD version does not match the PLAN handback artifact VERSION.',
      auto_flow: false,
      build_started: false,
      expected: version,
      provided: confirm.plan_artifact_version,
    };
  }

  return {
    ok: true,
    auto_flow: false,
    build_started: false, // BUILD is authorized, not auto-started here
    build_authorized: true,
    confirmation: confirm,
    skill: 'Foreman',
    plan_artifact_version: confirm.plan_artifact_version,
  };
}

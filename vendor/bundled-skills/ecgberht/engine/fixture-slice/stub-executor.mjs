/**
 * Wave 2 — STUB executor.
 *
 * NAMED as stub in every artifact. Refuses unconfirmed commissions.
 * Returns a canned validated handback. Can NEVER be read as the G4 verdict
 * (explicit g4_eligible: false / not_g4_verdict: true / executor: 'STUB').
 *
 * Zero real spend. Zero process spawn. Fixture-only.
 */

import {
  buildHandbackReceipt,
  validateReceipt,
} from '../receipt-validate.mjs';
import { makeFailure } from './failure-states.mjs';

/** Every stub artifact carries this label. */
export const STUB_LABEL = 'STUB';

export const STUB_EXECUTOR_ID = 'fixture-slice-stub-executor';

/**
 * Stamp STUB honesty fields onto any artifact.
 * @param {object} artifact
 */
export function stampStub(artifact) {
  return {
    ...artifact,
    executor: STUB_LABEL,
    executor_id: STUB_EXECUTOR_ID,
    stub: true,
    STUB: true,
    g4_eligible: false,
    not_g4_verdict: true,
    g4_verdict: 'NOT_APPLICABLE_STUB',
    message_g4:
      'This artifact is from the Wave-2 FIXTURE STUB executor — it is not G4 evidence and must never be read as g4-verdict PASS.',
  };
}

/**
 * Build the canned validated handback for a confirmed commission.
 * @param {object} commission confirmed fixture commission
 */
export function buildCannedHandback(commission = {}) {
  const receipt = buildHandbackReceipt({
    as_of: commission.confirmed_at?.slice?.(0, 10) ?? new Date().toISOString().slice(0, 10),
    active_effort: commission.step_name ?? commission.step_id ?? 'fixture-stage',
    why_next: 'Stub handback complete — deterministic reflection + next-stage proposal should emit.',
    grasscatch_why: null,
    tool_depth_why: `STUB executor at depth ${commission.depth_cell ?? 'LITE'} — no real specialist ran.`,
    human_wait: 'none',
    uncertainty_flags: ['fixture-only', 'stub-executor'],
    skill: commission.skill ?? 'researchPrime',
    depth: commission.depth_cell ?? 'LITE',
    commission_id: commission.proposal_id ?? null,
    partial: false,
  });
  return stampStub({
    ...receipt,
    kind: 'handback',
    canned: true,
    step_id: commission.step_id ?? null,
    fixture_only: true,
  });
}

/**
 * Invoke the stub executor.
 *
 * @param {{
 *   commission: object,
 *   authCtx?: object|null,
 * }} opts
 * @returns {object}
 */
export function runStubExecutor(opts = {}) {
  const commission = opts.commission;
  if (!commission || typeof commission !== 'object') {
    return stampStub(
      makeFailure('stub-handback-invalid', {
        error: 'stub_requires_commission',
        message: 'STUB executor requires a commission object.',
      }),
    );
  }

  // Refuse unconfirmed commissions — honesty law.
  if (commission.confirmed !== true) {
    return stampStub({
      ok: false,
      code: 'confirm-refused',
      status: 'EXEC_REFUSED_UNCONFIRMED',
      error: 'EXEC_REFUSED_UNCONFIRMED',
      message:
        'STUB: Commission not confirmed — nothing launched, nothing spent.',
      refused: true,
      commission_id: commission.proposal_id ?? null,
      step_id: commission.step_id ?? null,
      fixture_only: true,
    });
  }

  const handback = buildCannedHandback(commission);
  const validated = validateReceipt(handback);
  if (!validated.ok) {
    return stampStub(
      makeFailure('stub-handback-invalid', {
        error: validated.error ?? 'handback_invalid',
        message: validated.message ?? 'STUB canned handback failed validation.',
        issues: validated.issues,
        handback,
      }),
    );
  }

  return stampStub({
    ok: true,
    status: 'STUB_HANDBACK_OK',
    handback: validated.receipt,
    validation: { ok: true, schema_id: validated.schema_id },
    spend_usd: 0,
    model_calls: 0,
    processes_spawned: 0,
    fixture_only: true,
    message: 'STUB executor returned a canned validated handback — zero spend.',
  });
}

/**
 * Emit stub_handback event to the fixture ledger.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} result runStubExecutor result
 */
export function emitStubHandback(ledger, result) {
  return ledger.append(
    stampStub({
      kind: 'stub_handback',
      ok: result.ok === true,
      status: result.status,
      handback: result.handback ?? null,
      spend_usd: result.spend_usd ?? 0,
      model_calls: result.model_calls ?? 0,
      processes_spawned: result.processes_spawned ?? 0,
      refused: result.refused === true,
      error: result.error ?? null,
      fixture_only: true,
    }),
  );
}

/**
 * True when an artifact is honestly labelled STUB and not G4-eligible.
 * @param {object} artifact
 */
export function isHonestStubArtifact(artifact) {
  if (!artifact || typeof artifact !== 'object') return false;
  return (
    (artifact.executor === STUB_LABEL || artifact.STUB === true || artifact.stub === true) &&
    artifact.g4_eligible === false &&
    artifact.not_g4_verdict === true
  );
}

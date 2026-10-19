/**
 * Wave 2 — commission PROPOSAL rendering skill + seat + depth (shape only).
 *
 * Pure proposal — nothing executes until confirmed, and execution in this
 * wave is the labelled STUB executor. Seats come from injected prefs/env
 * (resolveSeats); no product model IDs hard-coded.
 */

import { normalizeCommissionSkill, COMMISSION_SKILLS } from '../commission.mjs';
import { resolveSeats } from '../seating.mjs';
import { authorize } from '../authorize.mjs';
import { makeFailure } from './failure-states.mjs';
import { claimedWho } from './batch-confirm.mjs';

export const FIXTURE_COMMISSION_PROPOSAL_SCHEMA = 'ecgberht-fixture-commission-proposal-v0';

/**
 * Propose a commission FOR a named scaffolding stage.
 *
 * @param {{
 *   step_id: string,
 *   skill: string,
 *   depth?: string|null,
 *   depth_cell?: string|null,
 *   seats?: object|null,
 *   prefs?: object|null,
 *   env?: object,
 *   scaffolding?: object|null,
 *   at?: string,
 * }} opts
 */
export function proposeFixtureCommission(opts = {}) {
  const step_id = opts.step_id ?? opts.step ?? null;
  if (!step_id || !String(step_id).trim()) {
    return makeFailure('confirm-refused', {
      error: 'commission_propose_requires_step',
      message: 'Commission is proposed FOR a scaffolding stage — pass step_id.',
    });
  }

  const skill = normalizeCommissionSkill(opts.skill);
  if (!skill) {
    return {
      ok: false,
      code: 'compile-failed',
      status: 'FIXTURE_UNKNOWN_SKILL',
      message: `Commission skill must be one of: ${COMMISSION_SKILLS.join(', ')}`,
      allowed_skills: [...COMMISSION_SKILLS],
    };
  }

  const depth_cell = opts.depth_cell ?? opts.depth ?? 'LITE';
  const seats =
    opts.seats && typeof opts.seats === 'object'
      ? opts.seats
      : resolveSeats({
          prefs: opts.prefs ?? {
            coding_family: 'claude',
            review_family: 'gemini',
            default_cli: 'claude',
          },
          env: opts.env,
        });

  if (seats && seats.ok === false) {
    return {
      ok: false,
      code: 'unknown',
      status: 'FIXTURE_SEATS_UNKNOWN',
      message: seats.message ?? 'Seat resolution failed — reported as unknown, not empty.',
      seats,
    };
  }

  const step =
    Array.isArray(opts.scaffolding?.steps)
      ? opts.scaffolding.steps.find((s) => s.step_id === step_id) ?? null
      : null;

  const at = opts.at ?? new Date().toISOString();
  const proposal = {
    schema: FIXTURE_COMMISSION_PROPOSAL_SCHEMA,
    kind: 'commission_proposal',
    proposal_id: `fixture-commission-${step_id}-${skill}`,
    step_id: String(step_id),
    step_name: step?.name ?? null,
    skill,
    depth_cell,
    seats: {
      coding_family: seats.coding_family ?? null,
      review_family: seats.review_family ?? null,
      coding_driver: seats.coding_driver ?? null,
      review_driver: seats.review_driver ?? null,
      cross_model: seats.cross_model ?? null,
      source: seats.source ?? 'prefs_or_defaults',
    },
    rendering: {
      skill,
      seat: seats.coding_driver ?? seats.coding_family ?? 'unknown',
      depth: depth_cell,
      summary: `Commission ${skill} at depth ${depth_cell} on seat ${seats.coding_driver ?? 'unresolved'} for stage ${step_id}.`,
    },
    requires_confirm: true,
    confirmed: false,
    fixture_only: true,
    at,
    message: `Steward proposes commissioning ${skill} for stage '${step_id}'. Confirm or refuse — nothing runs until confirm.`,
  };

  return { ok: true, proposal };
}

/**
 * Confirm a fixture commission proposal (records who; still no real spend).
 *
 * @param {{
 *   proposal: object,
 *   who: string|object,
 *   authCtx?: object|null,
 *   at?: string,
 * }} opts
 */
export function confirmFixtureCommission(opts = {}) {
  const proposal = opts.proposal;
  if (
    !proposal ||
    proposal.kind !== 'commission_proposal' ||
    proposal.requires_confirm !== true
  ) {
    return makeFailure('confirm-refused', {
      error: 'commission_confirm_requires_proposal',
      message: 'Confirm needs a fixture commission_proposal.',
    });
  }

  const who = normalizeWho(opts.who);
  if (!who) {
    return makeFailure('confirm-refused', {
      error: 'commission_confirm_requires_who',
      message: 'Commission confirm requires who (claimed identity).',
    });
  }

  if (opts.authCtx != null) {
    const decision = authorize('confirm', opts.authCtx);
    if (!decision.ok) {
      return makeFailure('confirm-refused', {
        error: decision.code ?? 'auth-refused',
        message: decision.message ?? 'Commission confirm refused at the auth seam.',
        auth: decision,
      });
    }
  }

  const at = opts.at ?? new Date().toISOString();
  const confirmed = {
    ...proposal,
    confirmed: true,
    requires_confirm: false,
    who,
    confirmed_at: at,
    fixture_only: true,
  };
  return { ok: true, confirmation: confirmed, proposal: confirmed };
}

/**
 * Emit commission_proposed / commission_confirmed fixture events.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} proposal
 */
export function emitCommissionProposed(ledger, proposal) {
  return ledger.append({
    kind: 'commission_proposed',
    proposal_id: proposal.proposal_id,
    step_id: proposal.step_id,
    skill: proposal.skill,
    depth_cell: proposal.depth_cell,
    seats: proposal.seats,
    rendering: proposal.rendering,
    requires_confirm: true,
    confirmed: false,
    fixture_only: true,
    at: proposal.at,
  });
}

/**
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} confirmation
 */
export function emitCommissionConfirmed(ledger, confirmation) {
  return ledger.append({
    kind: 'commission_confirmed',
    proposal_id: confirmation.proposal_id,
    step_id: confirmation.step_id,
    skill: confirmation.skill,
    depth_cell: confirmation.depth_cell,
    seats: confirmation.seats,
    who: confirmation.who,
    confirmed: true,
    fixture_only: true,
    at: confirmation.confirmed_at,
  });
}

function normalizeWho(who) {
  if (who == null) return null;
  if (typeof who === 'string' && who.trim()) return claimedWho(who.trim());
  if (typeof who === 'object' && who.claimed && String(who.claimed).trim()) {
    return {
      claimed: String(who.claimed).trim(),
      provenance: who.provenance ?? 'claimed_unauthenticated',
    };
  }
  return null;
}

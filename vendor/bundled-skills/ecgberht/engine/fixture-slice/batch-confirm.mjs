/**
 * Wave 2 — ONE batch confirmation of a scaffolding proposal, recording who.
 *
 * Gate decision 5 shape: who is claimed identity stamped unauthenticated.
 * Auth is exercised via the injected authorize(seam, ctx) hook when authCtx
 * is supplied (auth-ON lane). Hash-bound confirm: payload must carry the
 * content hash of the rendered proposal (TOCTOU foreshadow for Waves 8/9).
 */

import { authorize } from '../authorize.mjs';
import { makeFailure } from './failure-states.mjs';
import { contentHash } from './compile.mjs';

export const BATCH_CONFIRM_SCHEMA = 'ecgberht-fixture-batch-confirm-v0';

/**
 * Build the claimed_unauthenticated who stamp (gate decision 5).
 * @param {string} claimed
 * @returns {{ claimed: string, provenance: 'claimed_unauthenticated' }}
 */
export function claimedWho(claimed) {
  return {
    claimed: String(claimed),
    provenance: 'claimed_unauthenticated',
  };
}

/**
 * Batch-confirm a scaffolding proposal.
 *
 * @param {{
 *   proposal: object,
 *   who: string|{ claimed: string, provenance?: string },
 *   proposal_hash?: string,
 *   authCtx?: object|null,
 *   at?: string,
 * }} opts
 * @returns {{ ok: true, confirmation: object } | { ok: false, code: string, message: string }}
 */
export function batchConfirmScaffolding(opts = {}) {
  const proposal = opts.proposal;
  if (
    !proposal ||
    typeof proposal !== 'object' ||
    proposal.kind !== 'scaffolding_proposal' ||
    proposal.requires_batch_confirm !== true
  ) {
    return makeFailure('confirm-refused', {
      error: 'confirm_requires_scaffolding_proposal',
      message: 'Batch confirm needs a scaffolding_proposal with requires_batch_confirm.',
    });
  }
  if (proposal.confirmed === true) {
    return makeFailure('confirm-refused', {
      error: 'already_confirmed',
      message: 'Scaffolding already batch-confirmed — refuse double confirm.',
    });
  }

  const who = normalizeWho(opts.who);
  if (!who) {
    return makeFailure('confirm-refused', {
      error: 'confirm_requires_who',
      message: 'Batch confirm is a human decision — pass who (claimed identity).',
    });
  }

  // Hash-bound: expected hash is the proposal's own proposal_hash (or recomputed).
  const expectedHash =
    proposal.proposal_hash ??
    contentHash({
      schema: proposal.schema,
      kind: proposal.kind,
      goal: proposal.goal,
      steps: proposal.steps,
      oranges: proposal.oranges,
      requires_batch_confirm: proposal.requires_batch_confirm,
      confirmed: false,
      zero_model: proposal.zero_model,
      fixture_only: proposal.fixture_only,
    });
  const providedHash = opts.proposal_hash ?? proposal.proposal_hash;
  if (!providedHash || providedHash !== expectedHash) {
    return makeFailure('confirm-refused', {
      error: 'confirm-hash-mismatch',
      message:
        'Batch confirm refused — proposal content hash mismatch (TOCTOU guard).',
      expected_hash: expectedHash,
      provided_hash: providedHash ?? null,
    });
  }

  // Auth-ON seam: when authCtx is provided, authorize('confirm', authCtx) must pass.
  if (opts.authCtx != null) {
    const decision = authorize('confirm', opts.authCtx);
    if (!decision.ok) {
      return makeFailure('confirm-refused', {
        error: decision.code ?? 'auth-refused',
        message: decision.message ?? 'Confirm refused at the auth seam.',
        auth: decision,
      });
    }
  }

  const at = opts.at ?? new Date().toISOString();
  const confirmation = {
    schema: BATCH_CONFIRM_SCHEMA,
    kind: 'batch_confirmation',
    proposal_id: proposal.proposal_id,
    proposal_hash: expectedHash,
    who,
    credential_class: opts.authCtx?.credential_class ?? 'shared_secret_or_none',
    at,
    step_ids: (proposal.steps ?? []).map((s) => s.step_id),
    fixture_only: true,
    confirmed: true,
  };

  return { ok: true, confirmation, proposal: { ...proposal, confirmed: true } };
}

/**
 * Append batch_confirmed to the fixture ledger.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} confirmation
 */
export function emitBatchConfirmed(ledger, confirmation) {
  return ledger.append({
    kind: 'batch_confirmed',
    proposal_id: confirmation.proposal_id,
    proposal_hash: confirmation.proposal_hash,
    who: confirmation.who,
    credential_class: confirmation.credential_class,
    step_ids: confirmation.step_ids,
    at: confirmation.at,
    fixture_only: true,
  });
}

/**
 * @param {*} who
 * @returns {{ claimed: string, provenance: string }|null}
 */
function normalizeWho(who) {
  if (who == null) return null;
  if (typeof who === 'string' && who.trim()) {
    return claimedWho(who.trim());
  }
  if (typeof who === 'object' && who.claimed && String(who.claimed).trim()) {
    return {
      claimed: String(who.claimed).trim(),
      provenance: who.provenance ?? 'claimed_unauthenticated',
    };
  }
  return null;
}

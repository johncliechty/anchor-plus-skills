/**
 * Wave 2 — gate decision 4 shape at handback:
 *   IMMEDIATELY emit a ZERO-MODEL reflection receipt AND a ZERO-MODEL
 *   next-stage proposal, both deterministically rendered from ledger facts.
 *
 * No queued-proposal split. No model calls. No spend.
 * Richer narrative compile is a later-wave concern (session-open envelope).
 */

import { makeFailure } from './failure-states.mjs';
import { DEFAULT_ORANGES_PROMPTS } from './compile.mjs';

export const REFLECTION_RECEIPT_SCHEMA = 'ecgberht-fixture-reflection-receipt-v0';
export const NEXT_STAGE_PROPOSAL_SCHEMA = 'ecgberht-fixture-next-stage-proposal-v0';

/**
 * Emit the deterministic reflection receipt from handback + ledger facts.
 *
 * @param {{
 *   handback: object,
 *   commission?: object|null,
 *   scaffolding?: object|null,
 *   at?: string,
 * }} opts
 */
export function emitReflectionReceipt(opts = {}) {
  const handback = opts.handback;
  if (!handback || handback.kind !== 'handback') {
    return makeFailure('reflection-blocked', {
      error: 'reflection_requires_handback',
      message:
        'Reflection blocked — validated handback required (gate decision 4 shape).',
    });
  }

  const step_id = opts.commission?.step_id ?? handback.step_id ?? null;
  const steps = opts.scaffolding?.steps ?? [];
  const current = steps.find((s) => s.step_id === step_id) ?? null;
  const oranges =
    current?.oranges_annotations?.length
      ? [...current.oranges_annotations]
      : [...DEFAULT_ORANGES_PROMPTS];

  const at = opts.at ?? new Date().toISOString();
  const receipt = {
    schema: REFLECTION_RECEIPT_SCHEMA,
    kind: 'reflection_receipt',
    zero_model: true,
    zero_spend: true,
    deterministic: true,
    gate_decision: 4,
    step_id,
    skill: opts.commission?.skill ?? handback.skill ?? null,
    active_effort: handback.active_effort ?? null,
    why_next: handback.why_next ?? null,
    oranges_prompts: oranges,
    handback_summary: {
      active_effort: handback.active_effort,
      why_next: handback.why_next,
      human_wait: handback.human_wait,
      uncertainty_flags: handback.uncertainty_flags ?? [],
    },
    provenance: 'ledger-facts-deterministic',
    fixture_only: true,
    at,
    message:
      'ZERO-MODEL reflection receipt emitted at handback (gate decision 4) — not a queued split.',
  };

  return { ok: true, receipt };
}

/**
 * Emit the deterministic next-stage proposal from scaffolding + handback facts.
 * Gate decision 4: emitted AT handback, not deferred/queued as the only deliverable.
 *
 * @param {{
 *   handback: object,
 *   commission?: object|null,
 *   scaffolding?: object|null,
 *   at?: string,
 * }} opts
 */
export function emitNextStageProposal(opts = {}) {
  const handback = opts.handback;
  if (!handback || handback.kind !== 'handback') {
    return makeFailure('reflection-blocked', {
      error: 'next_stage_requires_handback',
      message:
        'Next-stage proposal blocked — validated handback required (gate decision 4 shape).',
    });
  }

  const steps = Array.isArray(opts.scaffolding?.steps) ? opts.scaffolding.steps : [];
  const currentId = opts.commission?.step_id ?? handback.step_id ?? null;
  const currentIdx = steps.findIndex((s) => s.step_id === currentId);
  const next =
    currentIdx >= 0 && currentIdx + 1 < steps.length ? steps[currentIdx + 1] : null;

  const at = opts.at ?? new Date().toISOString();

  if (!next) {
    // Honest terminal: no further stage — still an EMITTED proposal record naming that.
    const proposal = {
      schema: NEXT_STAGE_PROPOSAL_SCHEMA,
      kind: 'next_stage_proposal',
      zero_model: true,
      zero_spend: true,
      deterministic: true,
      gate_decision: 4,
      from_step_id: currentId,
      next_step_id: null,
      next_step: null,
      campaign_complete: true,
      requires_confirm: true,
      confirmed: false,
      oranges_prompts: [...DEFAULT_ORANGES_PROMPTS],
      provenance: 'ledger-facts-deterministic',
      fixture_only: true,
      at,
      message:
        'ZERO-MODEL next-stage proposal: no further stage in the confirmed scaffolding — campaign stages exhausted.',
    };
    return { ok: true, proposal };
  }

  const proposal = {
    schema: NEXT_STAGE_PROPOSAL_SCHEMA,
    kind: 'next_stage_proposal',
    zero_model: true,
    zero_spend: true,
    deterministic: true,
    gate_decision: 4,
    from_step_id: currentId,
    next_step_id: next.step_id,
    next_step: {
      step_id: next.step_id,
      name: next.name,
      done_when: next.done_when,
      oranges_annotations: next.oranges_annotations ?? [...DEFAULT_ORANGES_PROMPTS],
    },
    campaign_complete: false,
    requires_confirm: true,
    confirmed: false,
    oranges_prompts: next.oranges_annotations ?? [...DEFAULT_ORANGES_PROMPTS],
    provenance: 'ledger-facts-deterministic',
    fixture_only: true,
    at,
    message: `ZERO-MODEL next-stage proposal for '${next.step_id}' emitted at handback (gate decision 4).`,
  };

  return { ok: true, proposal };
}

/**
 * Append reflection_receipt fixture event.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} receipt
 */
export function appendReflectionReceipt(ledger, receipt) {
  return ledger.append({
    kind: 'reflection_receipt',
    ...receipt,
    kind: 'reflection_receipt',
  });
}

/**
 * Append next_stage_proposal fixture event.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} proposal
 */
export function appendNextStageProposal(ledger, proposal) {
  return ledger.append({
    kind: 'next_stage_proposal',
    ...proposal,
    kind: 'next_stage_proposal',
  });
}

/**
 * Gate decision 4 pair: both receipt AND proposal from one handback.
 * @param {object} opts same as emitReflectionReceipt / emitNextStageProposal
 */
export function emitHandbackPair(opts = {}) {
  const reflection = emitReflectionReceipt(opts);
  if (!reflection.ok) return reflection;
  const next = emitNextStageProposal(opts);
  if (!next.ok) return next;
  return {
    ok: true,
    reflection_receipt: reflection.receipt,
    next_stage_proposal: next.proposal,
    gate_decision: 4,
    zero_model: true,
    zero_spend: true,
    queued_proposal_split: false,
  };
}

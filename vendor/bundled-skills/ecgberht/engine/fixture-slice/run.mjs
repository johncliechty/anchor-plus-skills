/**
 * Wave 2 — end-to-end FIXTURE-ONLY vertical slice orchestrator.
 *
 * describe → propose → batch-confirm → commission → handback → reflection
 *   (+ deterministic next-stage proposal at handback — gate decision 4)
 *
 * Injected ledger only. Zero durable roadmap_events. Zero real spend.
 * Auth-ON: pass authCtx so confirm seams call authorize().
 */

import { createFixtureLedger } from './ledger.mjs';
import { requireFixtureRoot, resolveDurablePath } from './guard.mjs';
import { compileDescription, emitScaffoldingProposed } from './compile.mjs';
import {
  batchConfirmScaffolding,
  emitBatchConfirmed,
} from './batch-confirm.mjs';
import {
  proposeFixtureCommission,
  confirmFixtureCommission,
  emitCommissionProposed,
  emitCommissionConfirmed,
} from './commission-proposal.mjs';
import {
  runStubExecutor,
  emitStubHandback,
  STUB_LABEL,
} from './stub-executor.mjs';
import {
  emitHandbackPair,
  appendReflectionReceipt,
  appendNextStageProposal,
} from './reflection.mjs';
import { makeFailure } from './failure-states.mjs';

/**
 * Run the full fixture-only vertical slice.
 *
 * @param {{
 *   root: string,
 *   description: object,
 *   who: string|object,
 *   skill?: string,
 *   depth?: string,
 *   step_id?: string|null,
 *   authCtx?: object|null,
 *   prefs?: object|null,
 *   project_id?: string,
 *   at?: string,
 * }} opts
 */
export function runFixtureSlice(opts = {}) {
  // Durable path must never be resolved from this path.
  const root = requireFixtureRoot(opts.root);
  const ledger = createFixtureLedger({
    root,
    project_id: opts.project_id ?? 'fixture-slice-project',
  });

  const at = opts.at ?? '2026-08-02T00:00:00.000Z';
  const who = opts.who ?? 'john';
  const authCtx = opts.authCtx ?? null;

  // 1. Describe → compile coarse scaffolding + Oranges
  const compiled = compileDescription(opts.description ?? {});
  if (!compiled.ok) {
    ledger.append({
      kind: 'slice_failure',
      ...compiled,
      phase: 'compile',
      at,
    });
    return { ok: false, phase: 'compile', ledger, ...compiled };
  }
  const scaffolding = compiled.proposal;
  const propEv = emitScaffoldingProposed(ledger, scaffolding);
  if (!propEv.ok) {
    return { ok: false, phase: 'emit-scaffolding', ledger, ...propEv };
  }

  // 2. ONE batch confirmation with who
  const batch = batchConfirmScaffolding({
    proposal: scaffolding,
    who,
    proposal_hash: scaffolding.proposal_hash,
    authCtx,
    at,
  });
  if (!batch.ok) {
    ledger.append({
      kind: 'slice_failure',
      ...batch,
      phase: 'batch-confirm',
      at,
    });
    return { ok: false, phase: 'batch-confirm', ledger, scaffolding, ...batch };
  }
  emitBatchConfirmed(ledger, batch.confirmation);

  // 3. Commission proposal (skill + seat + depth)
  const step_id =
    opts.step_id ?? scaffolding.steps[0]?.step_id ?? null;
  const commissionProp = proposeFixtureCommission({
    step_id,
    skill: opts.skill ?? 'researchPrime',
    depth_cell: opts.depth ?? 'LITE',
    prefs: opts.prefs,
    scaffolding: batch.proposal,
    at,
  });
  if (!commissionProp.ok) {
    ledger.append({
      kind: 'slice_failure',
      ...commissionProp,
      phase: 'commission-propose',
      at,
    });
    return {
      ok: false,
      phase: 'commission-propose',
      ledger,
      scaffolding: batch.proposal,
      ...commissionProp,
    };
  }
  emitCommissionProposed(ledger, commissionProp.proposal);

  // 4. Confirm commission (who + optional auth)
  const commissionConf = confirmFixtureCommission({
    proposal: commissionProp.proposal,
    who,
    authCtx,
    at,
  });
  if (!commissionConf.ok) {
    ledger.append({
      kind: 'slice_failure',
      ...commissionConf,
      phase: 'commission-confirm',
      at,
    });
    return {
      ok: false,
      phase: 'commission-confirm',
      ledger,
      ...commissionConf,
    };
  }
  emitCommissionConfirmed(ledger, commissionConf.confirmation);

  // 5. STUB executor → canned validated handback
  const stubResult = runStubExecutor({
    commission: commissionConf.confirmation,
    authCtx,
  });
  emitStubHandback(ledger, stubResult);
  if (!stubResult.ok) {
    return {
      ok: false,
      phase: 'stub-execute',
      ledger,
      stub: stubResult,
      executor: STUB_LABEL,
    };
  }

  // 6. Gate decision 4: reflection receipt AND next-stage proposal at handback
  const pair = emitHandbackPair({
    handback: stubResult.handback,
    commission: commissionConf.confirmation,
    scaffolding: batch.proposal,
    at,
  });
  if (!pair.ok) {
    ledger.append({
      kind: 'slice_failure',
      ...pair,
      phase: 'reflection',
      at,
    });
    return { ok: false, phase: 'reflection', ledger, ...pair };
  }
  appendReflectionReceipt(ledger, pair.reflection_receipt);
  appendNextStageProposal(ledger, pair.next_stage_proposal);

  const chat = ledger.assertNoChatTurns();

  return {
    ok: true,
    phase: 'complete',
    fixture_only: true,
    executor: STUB_LABEL,
    spend_usd: 0,
    model_calls: 0,
    scaffolding: batch.proposal,
    batch_confirmation: batch.confirmation,
    commission_proposal: commissionProp.proposal,
    commission_confirmation: commissionConf.confirmation,
    stub_handback: stubResult,
    reflection_receipt: pair.reflection_receipt,
    next_stage_proposal: pair.next_stage_proposal,
    gate_decision_4: true,
    queued_proposal_split: false,
    zero_chat: chat.ok,
    chat_assertion: chat,
    ledger,
    events: ledger.list(),
  };
}

/**
 * Expose durable-path refusal for tests (must throw).
 * @returns {never}
 */
export function sliceResolveDurablePath() {
  return resolveDurablePath('runFixtureSlice');
}

/**
 * Named failure helper re-export for slice callers.
 */
export { makeFailure };

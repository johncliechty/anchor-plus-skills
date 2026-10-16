/**
 * Wave 2 — FIXTURE-ONLY vertical slice public surface.
 *
 * Prove the SHAPE of criteria 1–4 end to end over a temp-directory ledger
 * before the spine, executor or UI exists. Ships nothing durable.
 */

export {
  FIXTURE_ONLY,
  DURABLE_PATH_REFUSED,
  resolveDurablePath,
  requireFixtureRoot,
  isFixtureSliceModule,
} from './guard.mjs';

export {
  FIXTURE_FAILURE_STATES,
  FIXTURE_FAILURE_CODES,
  failureStateFor,
  makeFailure,
  emptyDistinctFromUnknown,
} from './failure-states.mjs';

export {
  FIXTURE_LEDGER_SCHEMA,
  FIXTURE_EVENTS_FILE,
  FIXTURE_EVENT_KINDS,
  FIXTURE_FORBIDDEN_KINDS,
  createFixtureLedger,
  hashFileBytes,
  hashRoadmapEvents,
} from './ledger.mjs';

// Wave 14 production owns contentHash on the public barrel (handback-ingest).
// Fixture-local hash stays available under a fixture-prefixed name so the
// hygiene guard never ships fixture behaviour as the production API.
export {
  SCAFFOLDING_PROPOSAL_SCHEMA,
  DEFAULT_ORANGES_PROMPTS,
  contentHash as fixtureContentHash,
  compileDescription,
  emitScaffoldingProposed,
} from './compile.mjs';

export {
  BATCH_CONFIRM_SCHEMA,
  claimedWho,
  batchConfirmScaffolding,
  emitBatchConfirmed,
} from './batch-confirm.mjs';

export {
  FIXTURE_COMMISSION_PROPOSAL_SCHEMA,
  proposeFixtureCommission,
  confirmFixtureCommission,
  emitCommissionProposed,
  emitCommissionConfirmed,
} from './commission-proposal.mjs';

export {
  STUB_LABEL,
  STUB_EXECUTOR_ID,
  stampStub,
  buildCannedHandback,
  runStubExecutor,
  emitStubHandback,
  isHonestStubArtifact,
} from './stub-executor.mjs';

// Wave 14 production owns emitReflectionReceipt on the public barrel
// (engine/handback-ingest.mjs). Fixture-local reflection helpers keep their
// names here for the Wave-2 slice; the barrel re-exports only the fixture-
// unique symbols (emitNextStageProposal / append* / emitHandbackPair) so the
// hygiene guard never ships fixture behaviour as the production API.
export {
  REFLECTION_RECEIPT_SCHEMA as FIXTURE_REFLECTION_RECEIPT_SCHEMA,
  NEXT_STAGE_PROPOSAL_SCHEMA as FIXTURE_NEXT_STAGE_PROPOSAL_SCHEMA,
  emitReflectionReceipt as emitFixtureReflectionReceipt,
  emitNextStageProposal,
  appendReflectionReceipt,
  appendNextStageProposal,
  emitHandbackPair,
} from './reflection.mjs';

export { runFixtureSlice, sliceResolveDurablePath } from './run.mjs';

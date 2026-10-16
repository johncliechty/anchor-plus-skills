/**
 * Wave 21 — process-free surface for the shared handback-contract conformance suite.
 *
 * The suite itself lives under conformance/handback-contract/ (adapters may spawn
 * OS children). This module re-exports the pure / verdict surface so engine/
 * consumers and kill-gate tooling can import without pulling child_process.
 *
 * ENGINE LAW: this file must never import child_process.
 */

export {
  CLAUSE_NAMES,
  CLAUSE_DESCRIPTIONS,
  isClauseName,
  clauseFailureName,
} from '../conformance/handback-contract/clauses.mjs';

export {
  ADAPTER_METHODS,
  EXECUTOR_SLOTS,
  validateAdapter,
  isExecutorSlot,
} from '../conformance/handback-contract/adapter-interface.mjs';

export {
  REAL_WRITER_SOURCES,
  sourceShowsS6,
  loadWriterSource,
  evaluateWriteInterception,
  evaluateWriteDiscipline,
  probeRealWriterS6,
} from '../conformance/handback-contract/write-intercept.mjs';

export {
  CONFORMANCE_VERDICT_REL as SUITE_CONFORMANCE_VERDICT_REL,
  CONFORMANCE_WRITTEN_BY,
  conformanceVerdictPath as suiteConformanceVerdictPath,
  emptyConformanceVerdict,
  readConformanceVerdict,
  mergeExecutorResult,
  writeConformanceVerdictForExecutor,
  writeConformanceVerdict,
  proveRegenerateTwiceByteIdentical,
} from '../conformance/handback-contract/verdict.mjs';

export {
  evaluateClause,
  evaluateInjectedScenario,
  makeCannedStubAdapter,
} from '../conformance/handback-contract/suite.mjs';

/** Relative suite root (from skill pack). */
export const CONFORMANCE_SUITE_REL = 'conformance/handback-contract';

/** Property-gate id (Wave 21 / NS criterion 15). */
export const T_CONF_15 = 'T-CONF-15';

/**
 * Wave 3 — Ground truth II audit harnesses + S10 fix-item ledger.
 * Re-export surface for engine/index.mjs and tests.
 */

export {
  FIX_ITEM_LEDGER_SCHEMA,
  FIX_ITEM_LEDGER_REL,
  DEGRADED_REL,
  FIX_ITEM_RESIDUAL_CAP,
  FIX_ITEM_MAX_WAVES,
  FIX_ITEM_KIND,
  resolveLedgerPath,
  resolveDegradedPath,
  emptyFixItemLedger,
  readFixItemLedger,
  countsAgainstCap,
  residualCount,
  evaluateCap,
  appendFixItem,
  writeDegradedList,
  applyCapOrHalt,
  appendFixItemAtPath,
} from './fix-item-ledger.mjs';

export {
  A1_SEAM_ANCHORS,
  A1_SEAM_TABLE_REL,
  findExportLine,
  auditA1SourceWiring,
  auditA1CallShapes,
  runA1Audit,
  writeA1ProjectTree,
} from './a1-commission-wiring.mjs';

export {
  A2_FIXTURE_REL,
  A2_COVERAGE_TABLE_REL,
  A2_MARK,
  A2_DOSSIER_LEANING_IDS,
  resolveA2FixtureDir,
  classifyBriefAnswer,
  assertNoFalseAnswered,
  runA2Audit,
} from './a2-brief-coverage.mjs';

export {
  A4_PLAN_WINDOW,
  A4_FIX_WAVE,
  A4_DEFECT_REL,
  extractA4SourceEvidence,
  probeA4KillBetweenWrites,
  runA4Audit,
} from './a4-confirm-pair.mjs';

export {
  CRITERION_13_FIELDS,
  FIELD_MARK,
  PRODUCTION_SCAN_DIRS,
  DURABLE_DEFINITIONS,
  DURABLE_SYMBOLS,
  A5_LIVENESS_REL,
  A5_DERIVED_INGEST_REL,
  A5_FIELD_MATRIX_REL,
  A5_ATTENTION_REL,
  findProductionMentions,
  classifyDurableMentions,
  runDerivedIngestProbe,
  runAttentionDeliveryProbe,
  runA5Liveness,
  emitFieldMatrix,
  runA5Audit,
} from './a5-portfolio-liveness.mjs';

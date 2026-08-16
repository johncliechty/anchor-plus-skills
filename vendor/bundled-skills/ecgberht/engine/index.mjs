/**
 * Ecgberht engine entrypoint.
 * W1: closed verbs + pack loaders.
 * W2: Face+Strip protocol, heal law, A1 discovery, strip-first rank.
 * W3: closed verb bodies + write-authority enforcement + harness canaries.
 * W4: dispatch table, LITE bias, structured receipts (override/depth/soft-vet).
 * W5 (legacy skill-plan): compose-only commission adapters + subscription seating.
 * Wave 5 (steward-handoff v3): decision records, G2/G3/G5/G6 spikes, cost
 *      model, deriveCommissionableSkills, SC6 feasibility verdict.
 * W6: verification pack, Grasscatcher ledger, Stage-2 freeze, canary pack.
 * TW1: Campaign Roadmap — append-only roadmap_events + derived projection.
 * TW2: Decision Packet / brief engine — Q1–Q12 deterministic retrieval,
 *      seen receipt delta anchor, read-only Anchor knowledge, precompute cache.
 * TW3: Commission propose/confirm + M2 job lifecycle receipts — jobs compose
 *      Anchor job_runner; queued→running→done|failed|orphaned|reaped;
 *      commission_abnormal receipt; commission_bind/status_flip via the
 *      Roadmap single writer. No in-process Foreman/Shark loops.
 * TW4: Dialogue compile layer (R2 §4.3 v1 act table; refuse-with-proposal;
 *      ephemeral dialogue store — no durable chat ledger) + seat hop
 *      (seat_hop receipt who/when/from→to; titlebar switcher wired to
 *      Anchor prefs claude/gemini/grok; non-event — no re-brief).
 * TW5: Seal chamber view model (wireframes v2.1 Screen 1) — goal bar ·
 *      Roadmap rail · ⏱ run block · steward-first conversation, composed
 *      from the closed verb bodies (CLI parity structural); rendered by the
 *      Anchor-dev docked overlay mount, never a v1 instrument card sheet.
 * TW6: High Seat view model (Screens 0+2) — raise queue (R2 §4.5, one raised
 *      at a time, ⚑ badge = queue length as the only ambient signal), spoken
 *      capacity balancing (annex A1/A3, override = receipt, no fake meters),
 *      Bring-it-up in-overlay hop (Option P path passport, cached packet) —
 *      plus the Decision Packet view (Screen 3): goal card always first,
 *      exactly one question, artifact display MVP (HTML inline best-effort,
 *      never a bare path), answers move the Roadmap via the single writer.
 * TW7: Standing up & honest states (Screen 4) — new-ground chamber (goal
 *      asked, never invented; Face+Strip created from templates on confirm
 *      ONLY), capacity-unknown hard-stop (spoken, exactly three honest
 *      options, no silent FULL, no meters), thin-evidence beat (honest
 *      unknown + constructive offer) — plus the TW7 canaries: junction
 *      realpath-before-prefix toward release freezes fails CI, and the
 *      second-task-DB canary keeps E5 the sole ledger.
 * TW8: Progressive-enhancement HARD GATE (voice / living animation /
 *      calendar-email open ONLY on TW5–TW6 spine green — structural probes
 *      over the shipped chambers — PLUS explicit literal-true config; any
 *      attempt before the gate refuses) + E7 recorded NOT built: parked
 *      Roadmap stub steps appended via the TW1 single writer, a refuse for
 *      any connector use, and the E7 not-built canary (connector marker +
 *      import/network call in engine sources is a red build — no OAuth code).
 */

export {
  SPELLING,
  CLOSED_VERBS,
  PRIMARY_VERBS,
  VERB_ALIASES,
  isClosedVerb,
  refuseUnknownVerb,
  resolvePrimaryVerb,
} from './verbs.mjs';

// Junction/symlink-safe direct-invocation guard (sleep cycle 2026-08-04, promoted from
// gandalf journal 0275). Ecgberht is registered AS a junction, so this is load-bearing:
// both bin/ CLIs were silent no-ops when invoked via ~/.claude/skills/ecgberht.
export { isDirectInvocation, realOrResolve } from './direct-invocation.mjs';

// The STEWARD PORTFOLIO surface (2026-08-04). Second closed surface, separate from
// CLOSED_VERBS by design. Exported because it had NO production entry point at all:
// `register` is the only path that mints a project marker, a minted project_id is the
// only thing that indexes, and the index is what the High Seat reads — so with no
// caller the portfolio altitude could never work. See engine/steward-surface.mjs.
export {
  STEWARD_SURFACE,
  WIRED_STEWARD_VERBS,
  UNWIRED_STEWARD_VERBS,
  runStewardVerb,
  refuseUnknownStewardVerb,
  refuseUnwiredStewardVerb,
} from './steward-surface.mjs';

export {
  skillRoot,
  loadJsonRelative,
  loadTextRelative,
  loadStripSchema,
  loadReceiptSchema,
  loadFaceMarkers,
  loadDispatchTableSeed,
  loadStripFixture,
  loadRoadmapSchema,
  loadRoadmapTemplate,
  loadRoadmapFixture,
  loadE7StubTemplate,
  loadGrasscatcherLedgerFixture,
  loadStage2FreezeFixture,
  loadFaceTemplate,
  loadStripTemplate,
  loadPackSurfaces,
} from './load.mjs';

export {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  STRIP_SCHEMA_ID,
  FACE_NARRATIVE_FIELDS,
  resolveProjectPath,
  extractStripFence,
  hasStripFenceMarker,
  parseFaceDocument,
  parseStrip,
  loadProjectSurfaces,
  toStripProjection,
} from './face-strip.mjs';

export {
  FACE_REWRITABLE,
  STRIP_CLOCK_FIELDS,
  STRIP_HISTORY_FIELDS,
  STRIP_PROTECTED_FIELDS,
  rewriteFaceNarrative,
  mutateStripInPlace,
  appendStripInstrument,
  appendStripReceipt,
  // W9: the same authority, made durable and findable at the moment of writing.
  appendStripInstrumentDurable,
  appendStripReceiptDurable,
  stripEntryBytes,
  isStripClockPatch,
} from './write-authority.mjs';

export {
  HEAL_LAW,
  HEAL_LAW_NOTES,
  assessDrift,
  healResync,
  applyNegativeHeartbeat,
  chatCannotInventTruth,
  repairFenceFromStrip,
  loadFaceNarrativeFromMarkdown,
} from './heal.mjs';

export {
  ENV_STRIP_ROOTS,
  JUNK_DIR_NAMES,
  parseRootsFromEnv,
  parseRootsFromCliArgs,
  resolveDiscoveryRoots,
  isJunkDirName,
  findStripJson,
  findStripFenceInFace,
  discoverInDirectory,
  discoverStrips,
} from './discovery.mjs';

export {
  CAPACITY_UNKNOWN_PENALTY,
  STARVATION_DAY_WEIGHT,
  HUMAN_WAIT_BOOST,
  NEGATIVE_HEARTBEAT_PENALTY,
  stripProjectionForRank,
  scoreStripProjection,
  rankPortfolioStripFirst,
  rankRequiredFullFace,
} from './rank.mjs';

export {
  RECEIPT_SCHEMA_ID,
  RECEIPT_KINDS,
  SEEN_ALTITUDES,
  OVERRIDE_REASON_FIELDS,
  HANDBACK_REQUIRED_FIELDS,
  COMMISSION_ABNORMAL_FIELDS,
  SEAT_HOP_RECEIPT_FIELDS,
  FACE_CONFIRM_RECEIPT_FIELDS,
  isMonologueOnly,
  validateReceipt,
  buildGrasscatchReceipt,
  buildDepthReceipt,
  buildOverrideReceipt,
  buildHandbackReceipt,
  buildCommissionAbnormalReceipt,
} from './receipt-validate.mjs';

export {
  DISPATCH_OUTCOMES,
  DISPATCH_DIMENSIONS,
  DEFAULT_BIAS,
  BUILTIN_CELLS,
  loadDispatchTable,
  normalizeTable,
  extractDispatchSignals,
  cellSpecificity,
  cellMatches,
  lookupDispatch,
  suggestDepthFromStrip,
  applyDepthOverride,
} from './dispatch-table.mjs';

export {
  SEAT_FAMILIES,
  SUBSCRIPTION_DRIVERS,
  PRODUCTION_SEAT_DRIVERS,
  PRODUCT_MODEL_ID_PATTERNS,
  familyToSubscriptionDriver,
  normalizeFamily,
  resolvePrefsCandidatePaths,
  loadAnchorPrefsFromDisk,
  loadAnchorPrefs,
  findProductModelIds,
  resolveSeats,
  isProductionSeatSafe,
} from './seating.mjs';

export {
  COMMISSION_SKILLS,
  COMMISSION_ADAPTERS,
  FORBIDDEN_REIMPLEMENT_EXPORTS,
  normalizeCommissionSkill,
  buildCommission,
  interpretHandback,
  validateHandback,
  getCommissionAdapter,
  commissionResearchPrime,
  commissionCrucible,
  commissionForeman,
  commissionGandalf,
  commissionJumper,
  runBoundaryCanaries,
} from './commission.mjs';

export {
  ROADMAP_FILE_NAME,
  ROADMAP_SCHEMA_ID,
  ROADMAP_EVENT_KINDS,
  ROADMAP_EVENTS_MAX,
  ROADMAP_STEP_STATUSES,
  ROADMAP_PROJECTION_FIELDS,
  ROADMAP_SET_FIELDS,
  FLIP_RECEIPT_FIELDS,
  ROADMAP_SINGLE_WRITER,
  parseRoadmap,
  emptyRoadmap,
  normalizeProjectionStep,
  buildRoadmapProjection,
  isValidFlipReceipt,
  validateRoadmap,
  healRoadmap,
  appendRoadmapEvent,
  appendRoadmapEventDurable,
  mutateRoadmapProjectionInPlace,
  loadProjectRoadmap,
  writeProjectRoadmap,
  verbRoadmapShow,
  verbRoadmapPropose,
  verbRoadmapSet,
} from './roadmap.mjs';

export {
  SPINE_LOCK_HELPER,
  SPINE_ATOMIC_WRITE,
  SPINE_LEDGER_FILE,
  ROADMAP_EVENT_KINDS_VERSION,
  SPINE_EVENT_KINDS,
  TYPED_STORES,
  ROADMAP_EVENTS_MAX as SPINE_ROADMAP_EVENTS_MAX,
  SPINE_CODE,
  SPINE_TEXT,
  SPINE_SINGLE_WRITER,
  spineFailure,
  assertStoreDeclared,
  assertEventKindAllowed,
  roadmapLedgerPath,
  readRoadmapEventsBounded,
  findEventByClientId,
  appendRoadmapEventSpineLaw,
  appendRoadmapEventThroughSpine,
  writeRoadmapThroughSpine,
  writeStripThroughSpine,
  assertSpineDurableHelpersPresent,
  assertKindsAligned,
} from './ledger-spine.mjs';

export {
  JOB_SCHEMA_ID,
  COMMISSION_PROPOSAL_SCHEMA_ID,
  JOB_LIFECYCLE_STATES,
  JOB_TERMINAL_STATES,
  JOB_ABNORMAL_TERMINALS,
  JOB_LIFECYCLE_TRANSITIONS,
  ANCHOR_JOB_COMPOSE,
  COMMISSION_PRIMARY_UX,
  proposeCommission,
  confirmCommission,
  advanceJobLifecycle,
  classifyTerminalObservation,
  observeJobTerminal,
  markJobRunning,
  verbCommissionPropose,
  verbCommissionConfirm,
} from './job-lifecycle.mjs';

// Wave 11 — Commission proposal (table-bound, seats law, executor seam, G4+SC6)
export {
  COMMISSION_PROPOSAL_SCHEMA,
  COMMISSION_IDEMPOTENCE_KEY,
  COMMISSION_PRECONDITION_HALT,
  SC6_HALT_NAME,
  DEPTH_TOKEN_BUDGET,
  COMMISSION_CODE,
  COMMISSION_TEXT,
  commissionFailure,
  commissionFailureTable,
  readSc6Feasibility,
  assertCommissionPreconditions,
  loadSkillsTable,
  selectCommissionableSkill,
  ANCHOR_DEFAULT_CLI_VALUES,
  mapDefaultCliToSeat,
  assertDefaultCliMapping,
  hasSeatCollision,
  hashCommissionProposal,
  proposalHashBody,
  estimateCommissionSpend,
  proposeBoundCommission,
  setCommissionExecutor,
  getCommissionExecutor,
  setInSessionExecutor,
  getInSessionExecutor,
  resetCommissionExecutors,
  executeCommission,
  clearCommissionIdempotenceCache,
  confirmBoundCommission,
  recomputeProposalHash as recomputeCommissionProposalHash,
  makeSkillsTableFixture,
} from './commission-proposal.mjs';

// Wave 12 — Progressive elaboration at stage START (criterion 5 / Master-Plan P5)
export {
  ELABORATION_SCHEMA,
  PREDICATE_ELEMENTS,
  PREDICATE_ELEMENT_LABELS,
  ELABORATION_EVENT_KINDS,
  ELAB_CODE,
  ELAB_TEXT,
  elabFailure,
  elaborationFailureTable,
  assertElaborationKindsAdmitted,
  hasNamedDeliverable,
  hasAcceptanceSentence,
  hasFaceAnchoredConstraint,
  evaluateCommissionability,
  targetedQuestionFor,
  assertQuestionNamesMissingElement,
  isResearchShapedGap,
  reconstructStepDetail,
  deriveTargetedQuestions,
  startStage,
  recordElaborationAnswers,
  declineElaboration,
  refuseOfferedCommission,
  listStageStarts,
  assertScaffoldingDemandsNoStageDetail,
  assertScaffoldSourceDemandsNoStageDetail,
  COMMISSIONABILITY_ELEMENTS,
} from './progressive-elaboration.mjs';

// Wave 13 — Host-agnostic status-ingestion seam + lease law + S12 outbox mediator
export {
  LEASE_TTL_MS,
  LEASE_STALE_FRACTION,
  LEASE_HYSTERESIS_MS,
  LEASE_RENEW_INTERVAL_MS,
  LEASE_STORE,
  RUN_LIVENESS,
  leaseStaleAfterMs,
  defaultLeaseMonoMs,
  resolveLeaseClocks,
  evaluateLeaseState,
  sampleLeaseAcrossBoundary,
  assertNoLeaseFlap,
} from './lease-law.mjs';

export {
  LIVENESS_PROBE_CACHE_TTL_MS,
  processIdentityKey,
  observeIdentity,
  createLivenessProbeCache,
  assertNoPerRenderTasklist,
} from './process-liveness.mjs';

export {
  OUTBOX_STORE,
  OUTBOX_ATOMIC_WRITE,
  OUTBOX_LOCK_HELPER,
  OUTBOX_SCHEMA_ID,
  OUTBOX_REL,
  OUTBOX_ACK_REL,
  OUTBOX_EVENT_KINDS,
  outboxPath,
  outboxAckPath,
  emptyOutbox,
  emptyAckCursor,
  readOutbox,
  appendOutboxRecord,
  readAckCursor,
  writeAckCursor,
  detectSequenceGap,
  pendingOutboxRecords,
  assertOutboxDurableHelpersPresent,
} from './status-outbox.mjs';

export {
  STATUS_INGESTION_SEAM,
  STATUS_PRODUCERS,
  STATUS_EVENT_SHAPES,
  STATUS_FAILURE_CODE,
  STATUS_FAILURE_TEXT,
  statusFailure,
  statusFailureTable,
  roadmapStatusForRunState,
  normalizeProducer,
  seamEventToStatusFlip,
  ingestStatusEvents,
  makeFixtureProducer,
  bindStatusToRoadmapProjection,
} from './status-ingestion.mjs';

export {
  MEDIATOR_PRODUCER_ID,
  makeOutboxProducer,
  drainOutboxThroughSeam,
  drainOutboxConverge,
  reconcileLeaseToStatus,
  assertMediatorDoesNotWriteLedger,
} from './status-mediator.mjs';

export {
  KILL9_TARGETS,
  reconcileSessionStatus,
  parkSession,
  healAfterKill9,
  reconcileAfterRestart,
  classifyStaleVsDead,
} from './status-reconciler.mjs';

export {
  GATE_SURFACE_KIND,
  W5_GATE_BUDGET_MS,
  buildGateSurfaceEvent,
  emitGateSurfaceToOutbox,
  surfaceGateThroughSeam,
  writeW13RealRunRecord,
  loadW5GateBudgetReference,
} from './gate-surface.mjs';

export {
  ANCHOR_STATUS_OUTBOX_MODULE_REL,
  ANCHOR_STATUS_OUTBOX_TEST_REL,
  ANCHOR_STATUS_OUTBOX_REQUIRED_SYMBOLS,
  anchorStatusOutboxSurface,
  resolveAnchorRootForOutbox,
  probeAnchorStatusOutboxSource,
} from './anchor-status-outbox-surface.mjs';

// Wave 7 — Commission dossier (S3) + confirm journal (A4 fix) + containment
export {
  DOSSIER_LOCK_HELPER,
  DOSSIER_ATOMIC_WRITE,
  DOSSIER_DIR_REL,
  CONFIRM_JOURNAL_DIR_REL,
  DOSSIER_INDEX_FILE,
  DOSSIER_SCHEMA_ID,
  CONFIRM_JOURNAL_SCHEMA_ID,
  CONFIRM_JOURNAL_IDEMPOTENCE_KEY,
  REPAIR_CONFIRM_JOURNAL_VERB,
  HONEST_UNKNOWN,
  DOSSIER_CODE,
  DOSSIER_TEXT,
  dossierFailure,
  dossierFailureTable,
  dossierIndexPath,
  dossierRecordPath,
  confirmJournalEntryPath,
  confirmJournalDir,
  isInsideProjectRoot,
  resolveContainedPath,
  emptyDossier,
  assertDossierDurableHelpersPresent,
  upsertDossier,
  recordLaunchOnDossier,
  recordHandbackOnDossier,
  readDossier,
  projectDossierRead,
  listDossiers,
  appendConfirmIntent,
  markConfirmApplied,
  readConfirmJournalEntry,
  listOpenConfirmJournal,
  applyConfirmIntent,
  rollbackConfirmIntent,
  repairConfirmJournal,
  confirmCommissionJournaled,
  a4DefectClosure,
  probeAtomConfirm,
  MAX_PATH as DOSSIER_MAX_PATH,
} from './commission-dossier.mjs';

export {
  ANCHOR_KNOWLEDGE_READ_ONLY,
  ANCHOR_STORE_DIR_NAME,
  ANCHOR_PROJECTS_DIR_NAME,
  ANCHOR_LANES,
  ANCHOR_DIRECTION_LAW,
  ENV_ANCHOR_ROOT,
  resolveAnchorRoot,
  isGroundedSummary,
  readAnchorProjectKnowledge,
  anchorConclusions,
  refuseAnchorStoreWrite,
} from './anchor-knowledge.mjs';

export {
  BRIEF_SCHEMA_ID,
  BRIEF_CACHE_SCHEMA_ID,
  BRIEF_CACHE_FILE_NAME,
  UNKNOWN_ANSWER,
  BRIEF_ALTITUDES,
  SEEN_RECEIPT_FIELDS,
  PROJECT_QUESTION_IDS,
  PORTFOLIO_QUESTION_IDS,
  BRIEF_QUESTIONS,
  buildSeenReceipt,
  findLastSeen,
  appendSeenReceipt,
  listJournalEntries,
  deltaSinceSeen,
  assembleBriefPacket,
  briefPhaseB,
  buildBriefCacheProjection,
  writeBriefCache,
  loadBriefCache,
  briefCacheStale,
  precomputeBriefCache,
  verbBrief,
  hashBriefContent,
  faceVersionOf,
  lastRoadmapEventAnchor,
} from './brief.mjs';

export {
  setAuthorizer,
  getAuthorizer,
  authorize,
  allowAllAuthorizer,
  makeTokenAuthorizer,
  makeLocalTrustAuthorizer,
  resetAuthorizer,
} from './authorize.mjs';

// Wave 8 — Session envelope (one confirmed budget before authoring spend).
// ENVELOPE_MAX_SPEND_USD is exported from cost-model.mjs (Wave 5); do not re-export.
export {
  ENVELOPE_MAX_COMPILES,
  ENVELOPE_TTL_MINUTES,
  ENVELOPE_TTL_MS,
  ENVELOPE_LOCK_HELPER,
  ENVELOPE_ATOMIC_WRITE,
  ENVELOPE_LEDGER_REL,
  ENVELOPE_SCHEMA_ID,
  ENVELOPE_TERMS_SCHEMA,
  ENVELOPE_IDEMPOTENCE_KEY,
  ENVELOPE_SPEND_KINDS,
  ZERO_SPEND_NEVER_QUEUE_KINDS,
  QUEUE_WITHOUT_ENVELOPE_KIND,
  ENVELOPE_CODE,
  ENVELOPE_TEXT,
  envelopeFailure,
  envelopeFailureTable,
  defaultMonoMs,
  resolveClocks,
  hashEnvelopePayload,
  renderBudgetTerms,
  currentBudgetTermsHash,
  envelopeLedgerPath,
  emptyEnvelopeLedger,
  assertEnvelopeDurableHelpersPresent,
  assertNoAnchorTokenEnvRead,
  isEnvelopeExpired,
  envelopeBalance,
  latestEnvelope,
  readEnvelopeState,
  confirmSessionEnvelope,
  priceEnvelopeSpend,
  debitSessionEnvelope,
  envelopeCoversCommission,
  commissionRequiresOwnConfirmation,
  resolveNoLiveEnvelopePath,
  queueNlPolishReflectionCompile,
  attemptEnvelopeSpend,
  checkEnvelopeBoundRelation,
} from './session-envelope.mjs';

// Wave 9 — Scaffolding authoring: dialogue → step_create, batch-confirm (hash-bound)
export {
  SCAFFOLD_PROPOSAL_SCHEMA,
  SCAFFOLD_COMPILE_POLICY,
  DEFAULT_ORANGES_PROMPTS as SCAFFOLD_DEFAULT_ORANGES_PROMPTS,
  STEWARD_AUTHORED_PROVENANCE,
  SCAFFOLD_IDEMPOTENCE_KEY,
  SCAFFOLD_CODE,
  SCAFFOLD_TEXT,
  scaffoldFailure,
  scaffoldFailureTable,
  hashScaffoldPayload,
  compileScaffoldDescription,
  validateScaffoldProposal,
  recomputeProposalHash,
  requireProjectFace,
  checkRoadmapHealth,
  assertNoAdversarialReviewReachable,
  assertZeroChatPersistenceStructural,
  proposeScaffolding,
  findOpenScaffoldProposal,
  findBatchConfirmByClientId,
  batchConfirmScaffolding,
  DEFAULT_ORANGES_PROMPTS,
  describeAndConfirmScaffolding,
  scanForChatTurns,
  readRoadmapLedgerBytes,
} from './scaffolding.mjs';

// Wave 10 — Face compile projection (Master-Plan P4 restored)
export {
  FACE_LOCK_HELPER,
  FACE_ATOMIC_WRITE,
  FACE_EVENTS_REL,
  SOURCE_TEXT_DIR_REL,
  FACE_EVENTS_SCHEMA,
  FACE_COMPILE_SCHEMA,
  FACE_EVENT_KINDS,
  COMPILE_MAX_PASSES,
  FACE_COMPILE_IDEMPOTENCE_KEY,
  COMPILE_CODE,
  COMPILE_TEXT,
  compileFailure,
  faceCompileFailureTable,
  hashSourceText,
  sourceTextBlobPath,
  faceEventsPath,
  emptyFaceEventsLedger,
  writeSourceTextBlob,
  readSourceTextBlob,
  resolveProvenanceSpan,
  readFaceEvents,
  assertFaceDurableHelpersPresent,
  hashFaceVersion,
  buildExclusionSet,
  projectFaceFromEvents,
  reproduceSourceFromProvenance,
  extractFaceCandidates,
  compilePass,
  runBoundedCompile,
  validateCompileOutput,
  diffFaceFields,
  queryCompileCostLedger,
  retractFaceFact,
  compileFace,
  applyIncrementalFaceRewrite,
  projectFaceParkRestartEquivalent,
  assertFaceKindsAdmitted,
} from './face-compile.mjs';

// Wave 4 — skill-owned durable handback contract + anti-stub G4 verdict
export {
  CONTRACT_VERSION,
  CONTRACT_VERSION as HANDBACK_CONTRACT_VERSION,
  HANDBACK_REL_DIR,
  HANDBACK_JSON_NAME,
  TERMINAL_MARKER_NAME,
  WRITE_DISCIPLINE,
  IDEMPOTENCE_KEY,
  EXEC_FAILURE_STATES,
  loadHandbackContractSchema,
  contractDescriptor,
  assertContractMatchesSchema,
  handbackDir,
  handbackJsonPath,
  terminalMarkerPath,
  validateHandbackBody,
  writeHandbackPair,
  writeHandbackWithoutMarker,
  isIngestable,
  readIngestableHandback,
  IngestIdempotenceRegistry,
} from './handback-contract.mjs';

export {
  TRIO_CLI_ENTRY_TOKENS,
  G4_VERDICT_REL,
  G4_EVIDENCE_REL,
  G4_HALT_NAME,
  G4_HALT_MESSAGE,
  pathSegmentNamesTrioEntry,
  cmdlineNamesTrioEntry,
  evaluateG4Evidence,
  collectEvidenceFromWorktree,
  g4VerdictPath,
  g4EvidencePath,
  writeG4Evidence,
  writeG4Verdict,
  recordG4FromEvidence,
  readG4Verdict,
  isQualifyingFallback,
  assertG4Precondition,
  sanitizeArtifactPath,
  sanitizeEvidenceForShip,
  observeProcCreateTime,
  observeProcessIdentity,
} from './g4-verdict.mjs';

export {
  ANCHOR_EXECUTOR_MODULE_REL,
  ANCHOR_EXECUTOR_TEST_REL,
  ANCHOR_EXECUTOR_REQUIRED_SYMBOLS,
  anchorExecutorSurface,
  resolveAnchorRootForSurface,
  probeAnchorExecutorSource,
} from './anchor-executor-surface.mjs';

// Wave 3 — Ground truth II: A1/A2/A4/A5 audit harnesses + S10 fix-item ledger
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
  A1_SEAM_ANCHORS,
  A1_SEAM_TABLE_REL,
  findExportLine,
  auditA1SourceWiring,
  auditA1CallShapes,
  runA1Audit,
  writeA1ProjectTree,
  A2_FIXTURE_REL,
  A2_COVERAGE_TABLE_REL,
  A2_MARK,
  A2_DOSSIER_LEANING_IDS,
  resolveA2FixtureDir,
  classifyBriefAnswer,
  assertNoFalseAnswered,
  runA2Audit,
  A4_PLAN_WINDOW,
  A4_FIX_WAVE,
  A4_DEFECT_REL,
  extractA4SourceEvidence,
  probeA4KillBetweenWrites,
  runA4Audit,
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
} from './audits/index.mjs';

// Wave 2 — FIXTURE-ONLY vertical slice (shape of criteria 1–4; non-crediting)
export {
  FIXTURE_ONLY,
  DURABLE_PATH_REFUSED,
  resolveDurablePath,
  requireFixtureRoot,
  isFixtureSliceModule,
  FIXTURE_FAILURE_STATES,
  FIXTURE_FAILURE_CODES,
  failureStateFor,
  makeFailure,
  emptyDistinctFromUnknown,
  FIXTURE_LEDGER_SCHEMA,
  FIXTURE_EVENTS_FILE,
  FIXTURE_EVENT_KINDS,
  FIXTURE_FORBIDDEN_KINDS,
  createFixtureLedger,
  hashFileBytes,
  hashRoadmapEvents,
  SCAFFOLDING_PROPOSAL_SCHEMA,
  // Wave 14: contentHash is production-owned (handback-ingest). Fixture keeps
  // its local helper on fixture-slice only — do not re-export it here (hygiene).
  compileDescription,
  emitScaffoldingProposed,
  BATCH_CONFIRM_SCHEMA,
  claimedWho,
  emitBatchConfirmed,
  FIXTURE_COMMISSION_PROPOSAL_SCHEMA,
  proposeFixtureCommission,
  confirmFixtureCommission,
  emitCommissionProposed,
  emitCommissionConfirmed,
  STUB_LABEL,
  STUB_EXECUTOR_ID,
  stampStub,
  buildCannedHandback,
  runStubExecutor,
  emitStubHandback,
  isHonestStubArtifact,
  // Wave 14 owns emitReflectionReceipt / production schemas on the barrel.
  // Fixture-local reflection helpers stay on fixture-slice (direct import);
  // emitNextStageProposal remains fixture-named (production = proposeNextStageDeterministic).
  emitNextStageProposal,
  appendReflectionReceipt,
  appendNextStageProposal,
  emitHandbackPair,
  runFixtureSlice,
  sliceResolveDurablePath,
} from './fixture-slice/index.mjs';

// Wave 14 — handback ingest + deterministic reflection / next-stage (gate decision 4)
export {
  REFLECTION_RECEIPT_SCHEMA,
  NEXT_STAGE_PROPOSAL_SCHEMA,
  HANDBACK_INGEST_SCHEMA,
  MULTI_SKILL_PROOF_SCHEMA,
  W14_EVENT_KINDS,
  QUARANTINE_REL,
  INGEST_REGISTRY_REL,
  QUARANTINE_ATOMIC_WRITE,
  QUARANTINE_LOCK_HELPER,
  DEFAULT_ORANGES_PROMPTS as W14_DEFAULT_ORANGES_PROMPTS,
  HANDBACK_CODE,
  HANDBACK_TEXT,
  handbackFailure,
  handbackFailureTable,
  stableStringify as w14StableStringify,
  contentHash,
  contentHash as w14ContentHash,
  assertW14KindsAdmitted,
  assertHandbackIngestDurableHelpersPresent,
  buildLedgerView,
  emitReflectionReceipt,
  proposeNextStageDeterministic,
  emitHandbackPairDeterministic,
  quarantineDir,
  quarantineEntryPath,
  ingestRegistryPath,
  readIngestRegistry,
  recordIngestKey,
  quarantineHandback,
  listQuarantine,
  nameMissingHandback,
  handbackIdempotenceKey,
  countEmittedForKey,
  ingestHandback,
  ingestValidatedHandbackBody,
  selectMultiSkillProofSkills,
  driveSkillToValidatedHandback,
  runMultiSkillProof,
  GOLDEN_REFLECTION_REL,
  GOLDEN_PROPOSAL_REL,
  loadGolden,
  goldenEmitterInputs,
} from './handback-ingest.mjs';

// Wave 15 — ONE boot/open-project pipeline (Master-Plan P7 rehydration)
export {
  PIPELINE_STAGES,
  OPEN_PROJECT_PIPELINE_MODULE,
  OPEN_PROJECT_PIPELINE_SCHEMA,
  FIRST_MESSAGE_SCHEMA,
  PIPELINE_CHECKPOINT_REL,
  GOLDEN_FIRST_MESSAGE_REL,
  BRIEF_CODE,
  BRIEF_TEXT,
  briefFailure,
  briefFailureTable,
  pipelineCheckpointPath,
  readPipelineCheckpoint,
  writePipelineCheckpoint,
  stageReconcile,
  stageIngest,
  stagePublish,
  stageCompose,
  healBeforeBrief,
  buildPostReconcileLedgerView,
  joinDossierIntoPacket,
  recordedFacts,
  composeFirstMessage,
  openProjectPipeline,
  openProjectAfterKillEverything,
  loadGoldenFirstMessage,
  goldenFirstMessageInputs,
  assertSessionOpenSurfacePresent,
} from './session-open.mjs';

export {
  ATTENTION_STATES,
  ATTENTION_READ_UNKNOWN,
  ATTENTION_CELL_REL,
  ATTENTION_ATOMIC_WRITE,
  ATTENTION_LOCK_HELPER,
  ATTENTION_CELL_SCHEMA,
  ATTENTION_EVENT_KIND,
  W16_EVENT_KINDS,
  ATTENTION_HYSTERESIS_MS,
  ATTENTION_CODE,
  ATTENTION_TEXT,
  ATTENTION_CALL_SITES,
  ATTENTION_CALL_SITE_TABLE,
  attentionFailureTable,
  attentionFailure,
  countWaitingOnJohnSteps,
  deriveWaitingSteps,
  deliverableProvenance,
  deriveAttention,
  applyAttentionAntiFlap,
  attentionEdgeHash,
  attentionCellPath,
  readAttentionCell,
  publishAttention,
  assertAttentionDurableHelpersPresent,
  assertW16KindsAdmitted,
  assertPublishCallSitePresent,
  assertHighSeatNeverPublishes,
  attentionCellBytes,
} from './attention.mjs';

export {
  STORAGE_ATOMIC_WRITE,
  STORAGE_LOCK_HELPER,
  appendRecordDurable,
  readRecords,
  captureLoadEvidence,
  listProcessesSample,
  assertDurableHelpersPresent,
} from './storage-primitive.mjs';

export {
  ACT_TABLE,
  DIALOGUE_ACT_IDS,
  DESTRUCTIVE_PATTERNS,
  DIALOGUE_STORE_POLICY,
  matchesDestructive,
  compileUtterance,
  refuseWithProposal,
  buildFaceConfirmReceipt,
  applyStillTheGoal,
  createDialogueStore,
  refuseDurableChatLedger,
} from './dialogue.mjs';

export {
  SEAT_HOP_CONTINUES_FROM,
  driverToFamily,
  currentSeatFamily,
  buildSeatHopReceipt,
  seatHop,
  nextTurnContext,
  titlebarSeatOptions,
  persistSeatToAnchorPrefs,
  applyTitlebarSeatSwitch,
  verbSeatHop,
} from './seat-hop.mjs';

export {
  SEAL_CHAMBER_SCHEMA_ID,
  SEAL_ICON_RELPATH,
  CHAMBER_MOUNT,
  ROADMAP_MARKERS,
  ROADMAP_MARKER_LABELS,
  CHAMBER_NEGATIVE_SURFACES,
  CHAMBER_FOOTER_STAMP,
  buildTitlebar,
  buildGoalBar,
  railStepFromProjection,
  buildRoadmapRail,
  buildRunBlock,
  buildOpeningMessage,
  buildGrasscatcherOffer,
  acceptGrasscatcherOffer,
  buildSeatSwitchDivider,
  buildProvenanceRecall,
  buildSaybox,
  chamberSpeak,
  assembleSealChamber,
  chamberAgreesWithStatus,
} from './seal-chamber.mjs';

export {
  PACKET_VIEW_SCHEMA_ID,
  PACKET_FOOTER_STAMP,
  ARTIFACT_RENDER_MODES,
  classifyArtifact,
  buildArtifactCard,
  buildPacketTitlebar,
  buildGoalReminderCard,
  buildWhereWeAreCard,
  buildSinceYouLookedCard,
  buildQuestionCard,
  answerPacketQuestion,
  assemblePacketView,
} from './packet-view.mjs';

export {
  HIGH_SEAT_SCHEMA_ID,
  HIGH_SEAT_ICON_RELPATH,
  HIGH_SEAT_MOUNT,
  RAISE_SEVERITY_TIERS,
  STARVE_THRESHOLD_DAYS_DEFAULT,
  MAX_RAISED_BLOCKS,
  HIGH_SEAT_NEGATIVE_SURFACES,
  HIGH_SEAT_FOOTER_STAMP,
  raiseSeverity,
  buildRaiseQueue,
  buildHighSeatTitlebar,
  buildRaiseBlock,
  tileStatePill,
  buildProjectTiles,
  buildBalancingCard,
  applyBalancingOverride,
  buildHighSeatSaybox,
  highSeatSpeak,
  bringItUp,
  closeHighSeat,
  enrichForRaise,
  assembleHighSeat,
} from './high-seat.mjs';

// Wave 17 — High Seat fold + badge path bounded (portfolio at a glance)
export {
  PORTFOLIO_MAX_ROWS,
  BADGE_FILES_OPENED_BOUND_CACHED,
  BADGE_FILES_OPENED_BOUND_RECOMPUTE,
  ROOT_DELIM,
  _ECGBERHT_ROOT_DELIM,
  BADGE_CACHE_REL,
  BADGE_CACHE_SCHEMA,
  GLANCE_SCHEMA,
  GLANCE_ROW_SCHEMA,
  GLANCE_FIELD_KEYS,
  GLANCE_CODE,
  GLANCE_TEXT,
  glanceFailureTable,
  mapBridgeGarbage,
  GUARDED_WRITE_CALLS,
  WriteAuthorityRefusal,
  writeAuthorityNoneFs,
  glanceIndexOnlyFs,
  withWriteAuthorityNone,
  partitionRootsByDelimiter,
  delimiterRoundTrip,
  bindGlanceField,
  buildGlanceRow,
  foldRowToRaiseItem,
  foldProjections,
  badgeCachePath,
  badgeCachePayload,
  writeBadgeCache,
  readBadgeCache,
  listAttentionCellsFromIndex,
  recomputeBadgeCache,
  buildBadgeFromIndex,
  assemblePortfolioGlance,
  ambientSignals,
  assertBridgeStdoutPurity,
  hashProjectTree,
  assertTreesByteIdentical,
  importClientPollConstants,
  assertBadgePathDoesNotWalk,
} from './high-seat-glance.mjs';

// Wave 18 — Chamber UI (steps, proposals, artifacts, corrections, I52)
export {
  CHAMBER_UI_SCHEMA,
  ARTIFACT_CORRECTION_SCHEMA,
  COMMISSIONED_ARTIFACT_CHROME,
  CHAMBER_SURFACES,
  CHAMBER_SURFACE_LABEL,
  CHAMBER_CODE,
  CHAMBER_TEXT,
  CHAMBER_STATE_TO_CODE,
  CHAMBER_POLLER_PATTERN,
  ECG_CHAMBER_MIN_MS,
  ECG_CHAMBER_MAX_MS,
  chamberUserText,
  chamberFailureTable,
  chamberFailure,
  importChamberPollConstants,
  auditChamberPoller,
  mapStepRow,
  buildStepsView,
  extractSpendPreview,
  classifyProposalKind,
  recomputeAnyProposalHash,
  buildProposalConfirmSurface,
  confirmProposalHashBound,
  isScaffoldExempt,
  extractBundleHash,
  renderCommissionedArtifactCard,
  buildArtifactView,
  resolveChamberArtifactPath,
  correctionHashBody,
  proposeArtifactCorrection,
  confirmArtifactCorrection,
  renderTypedConversationArtifact,
  buildReceiptRenderSurface,
  assembleChamberUi,
  injectChamberFailure,
  assertFailureTextsDistinct,
} from './chamber-ui.mjs';

export {
  parseVerbArgs,
  verbStatus,
  verbNext,
  verbUpdate,
  verbSoftVet,
  verbReceiptValidate,
  verbDepthSuggest,
  runClosedVerbBody,
  runHarnessCanaries,
  writeFaceNarrative,
} from './verb-bodies.mjs';

export {
  GRASSCATCHER_LEDGER_SCHEMA,
  GRASSCATCHER_DEFERRED_IDS,
  GRASSCATCHER_DEFERRED_LABELS,
  LEDGER_RECEIPT_FIELDS,
  loadGrasscatcherLedger,
  normalizeGrasscatcherLedger,
  auditGrasscatcherLedger,
  receiptForLedgerItem,
  buildAllLedgerReceipts,
  grasscatcherLabelsForStrip,
  assertNotMvpSurfaces,
} from './grasscatcher-ledger.mjs';

export {
  ANCHOR_V1_WRITE_MARKERS,
  runSpellingCanary,
  runAnchorV1WriteCanary,
  runComposeOnlyCanary,
  runCanaryPack,
  RELEASE_FREEZE_SEGMENTS,
  SECOND_TASK_DB_MARKERS,
  realpathJunctionAware,
  isFreezeSegment,
  freezeSegmentIn,
  isReleaseFreezeRealpath,
  runJunctionCanary,
  runSecondTaskDbCanary,
  runCanaryPackTw7,
} from './canary-pack.mjs';

export {
  STAND_UP_SCHEMA_ID,
  STAND_UP_VOICE,
  STAND_UP_ACTIONS,
  CAPACITY_CHOICES,
  CAPACITY_CHOICE_LABELS,
  CAPACITY_UNKNOWN_VOICE,
  projectHasSteward,
  buildStandUpChamber,
  assembleStandUp,
  standUpNotNow,
  fillFaceTemplate,
  confirmStandUp,
  buildCapacityUnknownChamber,
  requestFullRun,
  applyCapacityChoice,
  buildThinEvidenceBeat,
} from './stand-up.mjs';

export {
  PE_GATE_SCHEMA_ID,
  PE_FEATURES,
  PE_FEATURE_LABELS,
  PE_SPINE_WAVES,
  PE_GATE_LAW,
  defaultPeConfig,
  normalizePeConfig,
  probeTw5SealChamber,
  probeTw6HighSeat,
  checkSpineGreen,
  evaluatePeGate,
  requestProgressiveEnhancement,
  E7_STUBS_SCHEMA_ID,
  E7_STEP_STATUS,
  E7_NOT_BUILT,
  E7_CONNECTOR_MARKERS,
  e7StubSteps,
  appendE7StubSteps,
  refuseE7Connector,
  runE7NotBuiltCanary,
} from './pe-gate.mjs';

export {
  STAGE2_FREEZE_SCHEMA,
  FREEZE_DEPTH,
  loadStage2Freeze,
  getStage2FreezeSet,
  validateStage2Freeze,
  freezeSummaryForDocs,
} from './stage2-freeze.mjs';

export {
  verifyWriteAuthority,
  verifyStripFirstRank,
  verifyA1Discovery,
  verifyDispatchLiteBias,
  verifyOverrideRequiresReceipt,
  verifyReceiptValidate,
  verifyRefuseUnknown,
  verifySeatingPrefsMock,
  runVerificationPack,
} from './verification-pack.mjs';

// Wave 5 — decision records, spikes, cost model, skills table, SC6
export {
  IDENTITY_POLICY_SCHEMA,
  WHO_PROVENANCE,
  CREDENTIAL_CLASS_SHARED_SECRET,
  CREDENTIAL_CLASS_NONE,
  identityPolicyRecord,
  stampClaimedWho,
  normalizeClaimedWho,
  recordSpendConfirmationWho,
  renderWhoClaimedNotAuthenticated,
  assertWhoHonesty,
} from './identity-policy.mjs';

export {
  COST_MODEL_SCHEMA,
  COST_MODEL_DISCLAIMER,
  ENVELOPE_MAX_SPEND_USD,
  RATE_TABLE_USD_PER_1K,
  priceTokens,
  estimateTokens,
  priceCompile,
  percentile,
  summarizeCompileCosts,
  envelopeCoversP90,
  buildCostModelRecord,
} from './cost-model.mjs';

export {
  STEP_TYPE_MAP_SCHEMA,
  STEP_TYPES,
  STEP_TYPE_SKILL_MAP,
  stepTypeMapRecord,
  skillForStepType,
  confirmToPlan,
  confirmToBuild,
  attemptPlanToBuildFlow,
} from './step-type-map.mjs';

export {
  HALT_INVENTORY_SCHEMA,
  HALT_CLASSES,
  HALT_PATH_ROOTS,
  GATED_LANE_FRAGILITY,
  HALT_GATES,
  INVISIBLE_HALT_PROFILES_EXCLUDED_IN_FACE,
  skillHaltClass,
  buildHaltInventory,
} from './halt-inventory.mjs';

export {
  COMMISSIONABLE_SKILLS_SCHEMA,
  SC6_FEASIBILITY_SCHEMA,
  SC6_MIN_COMMISSIONABLE,
  COMMISSIONABLE_SKILLS_REL,
  SC6_FEASIBILITY_REL,
  HALT_INVENTORY_REL,
  normalizeG4EvidenceList,
  isExecutorProven,
  deriveCommissionableSkills,
  buildCommissionableSkillsPayload,
  evaluateSc6Feasibility,
  stableStringify,
  loadG4Evidence,
  loadHaltInventory,
  writeHaltInventory,
  writeCommissionableSkills,
  writeSc6Feasibility,
  detectCommissionableHandEdit,
  regenerateSkillsArtifacts,
} from './commissionable-skills.mjs';

export {
  G2_SPIKE_SCHEMA,
  DEFAULT_DOC_TRIO,
  isPlanShapedPath,
  renderDocTrioMember,
  runG2ArtifactSpike,
  writeG2SpikeVerdict,
} from './g2-artifact-spike.mjs';

export {
  G3_SPIKE_SCHEMA,
  CONFORMANT_HANDBACK_REL,
  TORN_HANDBACK_REL,
  buildRealTrioHandback,
  loadRealTrioHandback,
  corruptHandback,
  runG3HandbackSpike,
  writeG3SpikeVerdict,
  loadFixtureHandbacks,
} from './g3-handback-spike.mjs';

export {
  FACE_GLOSSARY_SCHEMA,
  AMENDMENT_DECISION_SCHEMA,
  CALIBRATION_SCHEMA,
  faceGlossaryRecord,
  amendmentVsRecommissionRecord,
  collectCompileSamples,
  buildCompileCostCalibration,
  emitAllWave5Artifacts,
} from './wave5-decisions.mjs';

// Wave 20 — In-session executor (IMPLEMENTATION #2; producer #2; S14; exec2)
export {
  INSESSION_MAX_CONCURRENT_RUNS,
  INSESSION_STORE,
  INSESSION_ATOMIC_WRITE,
  INSESSION_LOCK_HELPER,
  INSESSION_LEDGER_SCHEMA,
  INSESSION_LEDGER_REL,
  EXEC2_VERDICT_REL,
  EXEC2_EVIDENCE_REL,
  INSESSION_PRODUCER_ID,
  FORBIDDEN_CHILD_ENV,
  EXEC2_CODE,
  EXEC2_TEXT,
  exec2Failure,
  exec2FailureTable,
  setInSessionProcessHooks,
  getInSessionProcessHooks,
  resetInSessionProcessHooks,
  resetInSessionLiveTable,
  sessionLiveRunCount,
  buildChildEnv,
  observeChildEnv,
  argvCarriesNoToken,
  insessionLedgerPath,
  emptyInsessionLedger,
  readInsessionLedger,
  writeInsessionLedger,
  updateInsessionLedger,
  countLiveRuns,
  assertInsessionDurableHelpersPresent,
  emitInsessionStatusEvent,
  makeInsessionStatusProducer,
  renewInsessionLease,
  resolveCommissionCmdline,
  writeLaunchIntent,
  updateRunRecord,
  authorizeLaunch,
  executeInSession,
  completeInsessionRun,
  commissionKill,
  reconcileInSessionOrphans,
  listInsessionRunsForPipeline,
  installInSessionExecutor,
  resetInSessionExecutor,
  evaluateExec2Evidence,
  exec2VerdictPath,
  exec2EvidencePath,
  writeExec2Evidence,
  writeExec2Verdict,
  recordExec2FromEvidence,
  collectExec2EvidenceFromWorktree,
  validateHandbackAtContractPath,
} from './exec-insession.mjs';

// Wave 19 — Wave-0 kill gate (all 15 NS criteria; T-HOST-0 + conformance required)
export {
  KILL_GATE_SCHEMA,
  CRITERIA_TRACE_SCHEMA,
  KILL_GATE_REPORT_SCHEMA,
  T_HOST_0_VERDICT_REL,
  CONFORMANCE_VERDICT_REL,
  KILL_GATE_REPORT_REL,
  CRITERIA_TRACE_REL,
  KILL_GATE_ATOMIC_WRITE,
  KILL_GATE_LOCK_HELPER,
  KILL_GATE_CODE,
  KILL_GATE_TEXT,
  tHost0VerdictPath,
  conformanceVerdictPath,
  killGateReportPath,
  criteriaTracePath,
  readJsonArtifact,
  evaluateTHost0AtGate,
  evaluateConformanceAtGate,
  loadDegradedList,
  evaluateDegradedRule,
  assertG4Sc6AtKillGate,
  selectKillGateSkills,
  reportWhoPolicy,
  assertNoAnchorTokenInEngine,
  runAuthOutcomeSweep,
  runCampaignInvariantSweep,
  writeCampaignFace,
  runFreshProjectCampaign,
  runKillEverythingResumeLeg,
  buildCriteriaTraceabilityReport,
  writeCriteriaTraceabilityReport,
  evaluateKillGate,
  writeKillGateReport,
  assertKillGateDurableHelpersPresent,
  makePassingHostVerdicts,
} from './kill-gate.mjs';

// Wave 21 — shared handback-contract conformance suite (process-free surface)
export {
  CLAUSE_NAMES as CONFORMANCE_CLAUSE_NAMES,
  CLAUSE_DESCRIPTIONS as CONFORMANCE_CLAUSE_DESCRIPTIONS,
  clauseFailureName,
  validateAdapter as validateConformanceAdapter,
  evaluateWriteInterception,
  evaluateWriteDiscipline,
  evaluateClause as evaluateConformanceClause,
  evaluateInjectedScenario,
  emptyConformanceVerdict,
  readConformanceVerdict,
  writeConformanceVerdict,
  writeConformanceVerdictForExecutor,
  proveRegenerateTwiceByteIdentical,
  CONFORMANCE_SUITE_REL,
  CONFORMANCE_WRITTEN_BY,
  T_CONF_15,
} from './conformance-suite.mjs';

// Wave 22 — T-HOST-0 host-independence acceptance gate (NS criterion 14)
export {
  T_HOST_0_SCHEMA,
  T_HOST_0_SCRUB_ENV,
  T_HOST_0_STEP_NAMES,
  T_HOST_0_ATOMIC_WRITE,
  T_HOST_0_LOCK_HELPER,
  T_HOST_0_WRITTEN_BY,
  cheapProfileCliPath,
  scrubHostEnvironment,
  makeIsolatedHostHome,
  installNegativeEnvTraps,
  buildTHost0Verdict,
  writeTHost0Verdict,
  assertTHost0DurableHelpersPresent,
  resolveInSessionHooks,
  makeRealInSessionHooks,
  isHonestSeatSource,
  stepResult as tHost0StepResult,
  runTHost0Gate,
} from './t-host-0.mjs';

import {
  CLOSED_VERBS,
  isClosedVerb,
  refuseUnknownVerb,
  resolvePrimaryVerb,
  SPELLING,
  VERB_ALIASES,
} from './verbs.mjs';
import { parseRootsFromCliArgs } from './discovery.mjs';
import { parseVerbArgs, runClosedVerbBody } from './verb-bodies.mjs';

/**
 * Run a closed verb body. Unknown verbs → structured refuse (no plugin dispatch).
 * @param {string} verb
 * @param {string[]} [args]
 * @param {object} [inject] test injectors (surfaces, cwd, persist, env, …)
 * @returns {object}
 */
export function runVerb(verb, args = [], inject = {}) {
  if (!isClosedVerb(verb)) {
    return refuseUnknownVerb(verb);
  }

  const primary = resolvePrimaryVerb(verb);
  const parsed = parseVerbArgs(Array.isArray(args) ? args : []);
  const cli = parseRootsFromCliArgs(Array.isArray(args) ? args : []);

  // Merge CLI roots/project with parseVerbArgs (same tokens)
  const roots = parsed.roots.length ? parsed.roots : cli.roots;
  const project = parsed.project ?? cli.project;

  const opts = {
    ...parsed,
    roots,
    project,
    verb_name: verb,
    // Alias original argv name for update vs heartbeat / soft-vet vs grasscatch
    ...(VERB_ALIASES[verb] ? { verb_name: verb } : {}),
    ...inject,
  };

  // Prefer inject.roots / inject.project when provided
  if (inject.roots !== undefined) opts.roots = inject.roots;
  if (inject.project !== undefined) opts.project = inject.project;

  const body = runClosedVerbBody(primary, opts);
  // Ensure verb field reflects the invoked token (including aliases)
  if (body && typeof body === 'object' && body.verb == null) {
    body.verb = verb;
  } else if (body && typeof body === 'object') {
    body.verb = verb;
    body.primary = primary;
  }
  return body;
}

/**
 * CLI main: verb may lead or follow --roots/--project flags.
 * @param {string[]} argv process.argv.slice(2)
 * @returns {object}
 */
export function main(argv) {
  const tokens = Array.isArray(argv) ? argv : [];

  if (!tokens.length) {
    return {
      ok: false,
      error: 'missing_verb',
      spelling: SPELLING,
      message: `${SPELLING} requires a closed verb. Pass one of the closed list.`,
      closed_verbs: [...CLOSED_VERBS],
    };
  }

  const parsed = parseRootsFromCliArgs(tokens);
  // Prefer first non-flag token as verb (supports `status --roots X` and `--roots X status`)
  let verb = null;
  let verbIndex = -1;
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === '--roots' || t === '-R' || t === '--project' || t === '-p') {
      // skip flag and its value
      if (tokens[i + 1] && !tokens[i + 1].startsWith('-')) i++;
      continue;
    }
    if (t.startsWith('--roots=') || t.startsWith('--project=')) continue;
    // Other long options are not the verb
    if (t.startsWith('--') || t.startsWith('-')) {
      // value-taking flags already handled for roots/project; skip known pairs generically
      if (
        tokens[i + 1] &&
        !tokens[i + 1].startsWith('-') &&
        !t.includes('=')
      ) {
        // only skip value when this looks like a flag that takes one (heuristic: not boolean)
        const booleanFlags = new Set(['--dry-run', '--no-persist']);
        if (!booleanFlags.has(t)) i++;
      }
      continue;
    }
    verb = t;
    verbIndex = i;
    break;
  }

  if (!verb) {
    return {
      ok: false,
      error: 'missing_verb',
      spelling: SPELLING,
      message: `${SPELLING} requires a closed verb. Pass one of the closed list.`,
      closed_verbs: [...CLOSED_VERBS],
      cli_roots: parsed.roots,
      cli_project: parsed.project,
    };
  }

  const args = tokens.filter((_, i) => i !== verbIndex);
  return runVerb(verb, args);
}

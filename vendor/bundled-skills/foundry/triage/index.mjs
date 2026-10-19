// Public surface of @foundry/triage — re-exports shared core + lock + Stage-0 +
// Foreman inherit + mapping tables + researchPrime intake wire + Wave-6
// manifest / prose blocks / entry points / small repairs.
export {
  NS01_WAVE1_STAMP,
  MODEL_TIERS,
  DEPTH_BANDS,
  MODEL_TIER_VALUES,
  DEPTH_BAND_VALUES,
  ACCEPTED_DEPTH_SET,
  isModelTier,
  isProcessDepth,
  canonicalizeDepth,
  normalizeDepth,
  normalizeDepthStrict,
  unknownDepthError,
  normalizeTier,
  recommend,
} from './core.mjs';

export {
  LOCK_SOURCES,
  LOCK_SOURCE_VALUES,
  isLockSource,
  isLockRecord,
  createLockRecord,
  getLockedBand,
  applyLock,
  lockFromInteractive,
  lockFromHeadless,
} from './lock.mjs';

export {
  NS01_WAVE3_STAMP,
  COMPLEXITY_BANDS,
  depthToLegacyBand,
  legacyBandToDepth,
  assessComplexity,
  resolveStage0TriageLock,
  buildHandoffTriageEmit,
  mergeTriageIntoForemanConfig,
  isForemanTriageTrack,
  assertForemanConsumerShape,
} from './crucible-wire.mjs';

export {
  NS01_WAVE4_STAMP,
  MIN_REVIEWERS,
  REVIEWERS_BY_DEPTH,
  normalizeInheritedDepth,
  isRecognizedTriageTrack,
  inheritDepthFromHandoff,
  reviewersForDepth,
  inheritReviewerCount,
} from './foreman-wire.mjs';

export {
  NS01_WAVE5_STAMP,
  MAPPED_SKILLS,
  BAND_MAPPINGS,
  JUMPER_KILL_GATES_MIN,
  assertJumperKillGatesFloor,
  REAPER_PASSES_MIN,
  ZOMBIE_HUNTER_SAFETY_FLOOR,
  ceremonyLevelOrdinal,
  assertZombieHunterBandInvariants,
  LIT_REVIEW_SAFETY_FLOOR,
  LIT_REVIEW_UNKNOWN_DEPTH,
  LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED,
  assertLiteratureReviewBandInvariants,
  normalizeLiteratureReviewDepthStrict,
  literatureReviewPartialOverrideError,
  resolveLiteratureReviewBand,
  knobsForSkill,
  crucibleKnobs,
  foremanKnobs,
  researchPrimeKnobs,
  gandalfKnobs,
  jumperKnobs,
  resolveJumperDepthKnobs,
  ramanujanKnobs,
  resolveRamanujanDepthKnobs,
  assertRamanujanBandInvariants,
  tidyIdyKnobs,
  zombieHunterKnobs,
  resolveZombieHunterDepthKnobs,
  zombieHunterKnobProfile,
  literatureReviewKnobs,
  financialAnalystKnobs,
  legalBeagleKnobs,
  bandsInequal,
  knobsFingerprint,
  normalizeMappedSkill,
} from './mapping.mjs';

export {
  RESEARCHPRIME_SKILL_ID,
  recommendResearchPrimeIntake,
  resolveResearchPrimeIntakeLock,
  buildResearchPrimeIntakeExtension,
  finalizeIntakeExtensionOnGate1,
} from './researchprime-wire.mjs';

export {
  NS01_WAVE6_STAMP,
  ALL_SKILLS,
  SKILLS_MANIFEST,
  WAVE6_BLOCK_SKILLS,
  getSkillManifestEntry,
  assertManifestComplete,
  proseSkillIds,
  engineSkillIds,
} from './skills-manifest.mjs';

export {
  TRIAGE_BLOCK_BEGIN,
  TRIAGE_BLOCK_END,
  buildTriageBlockPayload,
  renderTriageBlock,
  renderAllTriageBlocks,
  renderGeneratedFile,
  generatedBlockFileName,
  normalizeGeneratedText,
  diffGenerated,
} from './prose-block.mjs';

export {
  entryPointContract,
  recommendForSkill,
  resolveSkillLock,
  knobsAfterLock,
  triageBlockForSkill,
  openSkillEntry,
} from './entry-points.mjs';

export {
  NS01_WAVE6_REPAIRS_STAMP,
  DESCRIPTION_DOC_BASENAMES,
  DESCRIPTION_DOC_PATTERNS,
  isDescriptionDocBasename,
  PROMPT_SIZE_MARKDOWN_FIRST_BYTES,
  shouldUseMarkdownFirst,
  repairsStatus,
} from './repairs.mjs';

// engine/launch/index.mjs — Wave 5: the launch surface, in one import.
//
// The tool OWNS its launch. Everything a caller needs to run tidy-idy over a
// folder and open its panel is here, and none of it imports Anchor.

// B5 P1: shared ceremony knobs (mapping sole truth) for launch + downstream.
export { resolveTidyIdyKnobs, pickTidyIdyDepth, tidyIdyKnobs } from '../triage-knobs.mjs';

export { tidyIdy, makeRescanHook, LAUNCH_STATUS, CLI_PATH } from './launch.mjs';
export { projectIdentity, formatIdentity, sameProject } from './identity.mjs';
export {
  evaluateCostGate, countTree, costConfig,
  GENERIC_EXCLUSIONS, DEFAULT_THRESHOLDS, COUNT_CAP,
} from './cost-gate.mjs';
export {
  openVerdictCache, nullVerdictCache, verdictKey, cachePathFor,
  CACHE_FILE, CACHE_VERSION,
} from './verdict-cache.mjs';
export {
  archiveRun, appendRunIndex, readRunIndex, renderReportMarkdown, ensureArchiveIgnored,
  archiveDirFor, runDirFor, runDirName, runsIndexPathFor, highestRunNumber,
  ARCHIVE_REL, ARCHIVE_FILES, RUNS_INDEX_DIRNAME, RUNS_INDEX_FILENAME,
} from './archive.mjs';
export {
  servePanel, checkOrigin, renderBootstrapPage,
  TOKEN_HEADER, CLOSE_REASON, BOOTSTRAP_PREFIX, LOOPBACK,
  DEFAULT_IDLE_TIMEOUT_MS, DEFAULT_HEARTBEAT_GAP_MS,
  GET_ENDPOINTS, POST_ENDPOINTS, MAX_BODY_BYTES,
} from './panel-server.mjs';
export { openPanel, panelLaunchSpec, browserCommand, ENVIRONMENT } from './opener.mjs';
export {
  writeBriefing, renderBriefingMarkdown, resolveTidyIdySkill, readSkillInstructions, skillSearchPaths,
  BRIEFING_FILENAME, SKILL_MD_SOURCE, TIDY_IDY_SKILL_NAME,
} from './briefing.mjs';
export {
  buildInvestigatorLaunchSpec, openInvestigator, terminalCommand, resolveEngine, engineChoices,
  openingPrompt, buildCommand, investigatorSlotDescriptor, makeInvestigateHook,
  INVESTIGATOR_ENGINE, DEFAULT_ENGINE, ENGINE_TEMPLATES,
} from './investigator.mjs';
export {
  consultTidyLock, guardMutatingLaunch, queueBehindTidyLock, ensureApplyEntryLock,
  tidyLockPathFor, TIDY_LOCK_REL, DECISION, ENTRY_LOCK_CODE,
} from './lock-authority.mjs';
export {
  buildTidyJobSpec, dispatchTidy, waitForPanelReady, parsePanelReady, readBootstrapFile,
  detectAnchorWorkspace, registerResourceClaimBestEffort, tidyIdyEntryPoint,
  FOLDER_CLAIM_LANE, TIDY_JOB_TYPE, PANEL_READY_EVENT,
} from './anchor-caller.mjs';
export {
  writeStatus, readStatus, renderStatusPage, statusPathFor, STATUS_FILE, PHASE,
  progressFor, STEP_PROGRESS, PHASE_PROGRESS, faviconDataUri, FAVICON_SVG,
} from './run-status.mjs';
export { serveRunStatus, LOOPBACK as STATUS_LOOPBACK } from './status-server.mjs';
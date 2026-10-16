// engine/apply/index.mjs — Wave 3: the Apply executor's library API.
//
// Deliberately a LIBRARY and nothing else. The HTTP control plane around it —
// capability token, persisted pending→applying→done state machine, replay
// idempotency — is Wave 6's, where a server exists. What ships here are the
// refusal predicates, so that when the server does arrive it is wiring, not
// safety: every reason Apply may not proceed is already decided in this
// directory and is already machine-readable.
//
//   applyApproved()  — canonical pipeline steps 1–5: ONE commit for git-held
//                      content PLUS ONE journaled Trash move-set for the rest
//   undoApply()      — revert-or-refuse, the decision-#8 SAVE compensation, and
//                      restore-from-Trash for the non-git-held half
//   checkNoClobber() — the system-wide no-clobber invariant (Wave 8 reuses it)
//   assertConsentScope() — the consent-scope invariant, as a porcelain class diff
//   acquireLock()    — the per-project-root advisory lock, honoured by scan too
//
// Wave 4 added the other two mutating surfaces, each with its own undo:
//   restoreFromTrash() — the journaled, idempotent, no-clobber move-back
//   applyBootstrap()   — secret-triage-FIRST `git init` + baseline commit B,
//                        undoable byte-for-byte while HEAD == B

export { applyApproved, appliedPaths, APPLY_REFUSAL, APPLY_STATUS } from './executor.mjs';
export { undoApply, testRevertCleanliness, UNDO_STATUS, UNDO_BRANCH, UNDO_REFUSAL } from './undo.mjs';

export {
  trashDirFor, trashFilesDirFor, ensureReportDirIgnored, preflightTrashMoveSet,
  executeTrashMoveSet, restoreFromTrash, readTrashLedger, listTrash, emptyTrash,
  TRASH_REFUSAL, TRASH_STATUS, TRASH_KIND, DEFAULT_TTL_MS,
} from './trash.mjs';
export {
  planBootstrap, buildBootstrapTile, applyBootstrap, undoBootstrap, canUndoBootstrap,
  BOOTSTRAP_STATUS, BOOTSTRAP_REFUSAL, BOOTSTRAP_KIND,
} from './bootstrap.mjs';

export { computeFindingId, stampFindingIds, buildFindingIndex, resolveApprovals, identityOf, FINDING_ID_PREFIX, IDENTITY_REFUSAL } from './identity.mjs';
export { acquireLock, withLock, readLock, lockPathFor, LOCK_FILE, LOCK_REFUSAL } from './lock.mjs';
// B5 P4: re-export entry-lock preflight so library callers share the same gate.
export {
  ensureApplyEntryLock, consultTidyLock, guardMutatingLaunch,
  ENTRY_LOCK_CODE, TIDY_LOCK_REL, DECISION, tidyLockPathFor,
} from '../launch/lock-authority.mjs';
export { openJournal, readJournal, findJournalForCommit, journalDirFor } from './journal.mjs';
export { revalidateFindings, assertHeadMatchesSnapshot, STALE_REASON } from './revalidate.mjs';
export { planFromFindings, orderOps, opPaths, declaredTransitions, findCaseCollisions, buildCommitMessage, parsePlanTrailer, OP_KIND } from './plan.mjs';
export { realizeWorkingTree, pendingPaths, REALIZE_STRATEGY } from './realize.mjs';
export { checkNoClobber, checkPathAgainstExpectation, expectationsFromJournal, manualRestoreCommand, CLOBBER_REASON } from './no-clobber.mjs';
export { capturePorcelainClasses, diffPorcelainClasses, assertConsentScope } from './consent-scope.mjs';
export { makeGitRunner, GitCommandError, lit, revBytes, revBlob, revSize, commitPaths } from './git-plumbing.mjs';
export { withTempIndex, makeTempIndex, modeForPath } from './temp-index.mjs';

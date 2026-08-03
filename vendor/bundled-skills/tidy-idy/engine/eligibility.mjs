// engine/eligibility.mjs — Wave 2: who is even allowed into the removal debate.
//
// Owned decision #3, as executable code: REMOVAL ELIGIBILITY IS DECIDED BEFORE
// THE LLM EVER SEES THE CANDIDATE. A path carrying staged or unstaged changes is
// hard-excluded from the REMOVE class here, upstream of the attacker/judge pass,
// so no verdict about it can exist to be approved by accident. It may still
// surface as a SAVE finding — "git does not hold this yet" is an argument for
// committing it, never for deleting it.
//
// Amendment A changes what happens to the UNTRACKED ones. The original design
// made untracked junk do a SAVE-then-remove-next-run dance (commit it so git
// holds it, then delete it in a later run) purely so that undo could be a git
// revert. With the Wave-4 reversible Trash that detour is gone: untracked
// content is removable in ONE step because the Trash move is itself reversible.
// So untracked candidates stay ELIGIBLE, routed to removalClass 'trash'.
//
// The exclusion log is not a debug aid. Every exclusion carries the VERBATIM
// porcelain line that caused it, because "the tool silently declined to consider
// this file" and "the tool considered it and git said it was dirty" are
// different claims and the panel must be able to prove which one happened.

import { TRACKING } from './porcelain.mjs';
import { toPosixRel } from './glob.mjs';

/** How an approved removal would actually be realised. */
export const REMOVAL_CLASS = Object.freeze({
  /** git holds the content: single-commit plan, undo = git revert (Wave 3). */
  GIT: 'git',
  /** git does not hold it: journaled Trash move-set, undo = restore (Wave 4). */
  TRASH: 'trash',
});

/** Classes that are hard-excluded from REMOVE: git holds an OLDER version only. */
const DIRTY_CLASSES = new Set([TRACKING.TRACKED_MODIFIED, TRACKING.STAGED, TRACKING.UNMERGED]);

const EXCLUSION_REASON = {
  [TRACKING.TRACKED_MODIFIED]: 'tracked with UNSTAGED modifications — git holds an older version, so a removal would destroy the newer working-tree content',
  [TRACKING.STAGED]: 'tracked with STAGED changes — git holds an older version, so a removal would destroy staged work',
  [TRACKING.UNMERGED]: 'UNMERGED (merge conflict in progress) — the path has no single settled content for a removal to be reversible against',
  unknown: "git's index could not be read, so this path's tracking class is UNKNOWN — the fail-safe is to exclude it from removal, never to assume it is safe",
};

/**
 * Partition candidates into removal-eligible and hard-excluded.
 *
 * @param {{candidates: string[], porcelain: object|null, secretBlocked?: Set<string>}} opts
 * @returns {{eligible: object[], excluded: object[], byPath: Map<string, object>}}
 */
export function computeRemovalEligibility({ candidates = [], porcelain = null, secretBlocked = new Set() } = {}) {
  const eligible = [];
  const excluded = [];
  const byPath = new Map();

  for (const raw of candidates) {
    const rel = toPosixRel(raw);

    // The secret gate runs upstream of everything, including this: a flagged
    // path is not "excluded from removal", it never entered the pipeline's LLM
    // half at all. Recorded here so the log accounts for every candidate.
    if (secretBlocked.has(rel)) {
      const rec = {
        path: rel,
        trackingClass: porcelain ? porcelain.classify(rel) : TRACKING.NON_GIT,
        reason: 'withheld by the pre-LLM secret gate — its content never reached an LLM stage, so no removal verdict about it can exist',
        porcelain: porcelain && porcelain.record(rel) ? porcelain.record(rel).raw : null,
        excludedFrom: 'remove',
      };
      excluded.push(rec);
      byPath.set(rel, rec);
      continue;
    }

    if (!porcelain) {
      // No repository. Amendment A: removals still work — through the Trash,
      // whose restore is the undo story git would otherwise have provided.
      const rec = {
        path: rel,
        trackingClass: TRACKING.NON_GIT,
        removalClass: REMOVAL_CLASS.TRASH,
        eligible: true,
        why: 'no repository at the run root — an approved removal moves the file into the reversible Trash (Amendment A), it is never deleted',
        porcelain: null,
      };
      eligible.push(rec);
      byPath.set(rel, rec);
      continue;
    }

    const cls = porcelain.classify(rel);
    const record = porcelain.record(rel);

    if (DIRTY_CLASSES.has(cls) || cls === 'unknown') {
      const rec = {
        path: rel,
        trackingClass: cls,
        reason: EXCLUSION_REASON[cls] || EXCLUSION_REASON.unknown,
        // Verbatim git evidence — the panel shows git's own line, not our gloss.
        porcelain: record ? record.raw : null,
        excludedFrom: 'remove',
        mayStillSurfaceAs: 'save',
      };
      excluded.push(rec);
      byPath.set(rel, rec);
      continue;
    }

    const rec = {
      path: rel,
      trackingClass: cls,
      removalClass: cls === TRACKING.TRACKED_CLEAN ? REMOVAL_CLASS.GIT : REMOVAL_CLASS.TRASH,
      eligible: true,
      why: cls === TRACKING.TRACKED_CLEAN
        ? 'tracked AND clean — git already holds exactly this content, so an approved removal lands as one commit and undoes as one git revert'
        : 'git does not hold this content — an approved removal moves it into the reversible Trash (Amendment A), one step, undo = restore-from-Trash',
      porcelain: record ? record.raw : null,
    };
    eligible.push(rec);
    byPath.set(rel, rec);
  }

  return { eligible, excluded, byPath };
}

/**
 * The one-line summary the envelope carries so a reader can tell at a glance
 * that exclusions happened without reading the whole log.
 */
export function summariseExclusions(excluded) {
  const byClass = {};
  for (const e of excluded) byClass[e.trackingClass] = (byClass[e.trackingClass] || 0) + 1;
  const parts = Object.entries(byClass).map(([k, v]) => `${v} ${k}`);
  return excluded.length
    ? `${excluded.length} candidate path(s) hard-excluded from the REMOVE class before the debate ran (${parts.join(', ')})`
    : 'no candidate was excluded from the REMOVE class';
}

export default { computeRemovalEligibility, summariseExclusions, REMOVAL_CLASS };

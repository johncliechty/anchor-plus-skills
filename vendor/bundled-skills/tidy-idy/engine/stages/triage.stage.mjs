// engine/stages/triage.stage.mjs — Wave 2: the universal pre-LLM gate, as a stage.
//
// POSITION IS THE FEATURE. This stage sits after `scan` (which establishes the
// in-scope set) and before EVERY stage that puts file content in front of a
// model — analyze, debate, compress. It produces two things:
//
//   ctx.state.triage      — the verdict for every in-scope path
//   ctx.state.llmBlocked  — the paths whose content must never reach an LLM
//
// and the downstream stages consume the second one as a hard filter. A gate
// that merely annotated findings would not be a gate: the leak happens when the
// analysis prompt is assembled, which is upstream of any finding existing.
//
// The gate reads EVERY in-scope file in full, including binaries and files past
// the LLM read cap, because the interesting case is exactly the key that sits
// beyond the cap where the LLM stages would never have looked.
//
// It emits `secret-blocked` findings, which are NOT approvable: action='blocked'
// is not in the actionable set, so no approval control can attach to one, and
// the remediation (per tracking class) is carried on the finding instead.

import { makeStageResult, STATUS } from '../envelope.mjs';
import { triageAll, buildRemediation, LLM_READ_CAP_BYTES } from '../secret-triage.mjs';
import { loadPorcelain, TRACKING } from '../porcelain.mjs';

export const triageStage = {
  name: 'triage',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // Content scanning does not consult git at all; only the REMEDIATION class
    // does (tracked vs untracked), and without a repo everything is non-git.
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — the secret gate is content+path based and runs identically; remediation is the non-git class (relocation + next-run override)',
  },

  async run(ctx) {
    const inScope = ctx.state.inScope || (ctx.state.topology && ctx.state.topology.inScope) || [];
    const snapshot = ctx.state.snapshot;
    const allow = (ctx.config && ctx.config.secrets && ctx.config.secrets.allow) || [];

    const porcelain = await loadPorcelain(ctx).catch(() => null);

    const verdicts = await triageAll({
      rootPath: ctx.rootPath,
      paths: inScope,
      fs: ctx.fs,
      sizes: snapshot ? snapshot.paths : {},
      allow,
    });
    ctx.state.triage = verdicts;

    const blocked = new Set();
    const quarantined = [];
    const findings = [];
    let unreadable = 0;
    let overridden = 0;

    for (const [rel, v] of verdicts) {
      if (v.readError) unreadable++;
      if (v.quarantine) quarantined.push({ path: rel, quarantine: v.quarantine, size: v.size });
      if (!v.flagged) continue;
      if (v.overridden) { overridden++; continue; }

      blocked.add(rel);
      const trackingClass = porcelain ? porcelain.classify(rel) : TRACKING.NON_GIT;
      findings.push({
        stage: triageStage.name,
        kind: 'secret-blocked',
        // NOT in ACTIONABLE_ACTIONS — there is deliberately no approval control
        // for this class, bulk or individual (owned decision #9).
        action: 'blocked',
        approvable: false,
        bulkApprovable: false,
        path: rel,
        absolutePath: v.absolutePath,
        trackingClass,
        blockedFrom: ['save', 'llm-context'],
        // Rule + location only. No matched text, not even partially masked.
        triggers: v.triggers,
        maskedTriggerText: v.maskedTriggerText,
        quarantine: v.quarantine,
        readError: v.readError,
        remediation: buildRemediation({ path: rel, trackingClass, triggers: v.triggers }),
        why: 'a secret-flagged path has no approval path in this tool — the alternatives below are the only routes forward',
      });
    }

    ctx.state.llmBlocked = blocked;
    ctx.state.quarantined = quarantined;

    // A file the gate could not read is a COVERAGE GAP, not an all-clear: it is
    // counted as skipped, which alone makes envelope.isClean unreachable.
    const notes = [
      `${verdicts.size} in-scope path(s) scanned by the pre-LLM secret gate (content AND path/filename)`,
      `the gate's reads are streaming and FULL-FILE — deliberately exempt from the ${Math.round(LLM_READ_CAP_BYTES / 1024)}KB LLM read cap and applied to binaries too, so a secret past the cap is still caught`,
      `${blocked.size} path(s) hard-blocked: their content is withheld from every LLM stage and from the SAVE class`,
    ];
    if (overridden) notes.push(`${overridden} flagged path(s) carry a .tidy-idy.toml [secrets] allow override from a previous run and are not blocked`);
    if (quarantined.length) notes.push(`${quarantined.length} path(s) quarantined by size/binary — individually confirmable, excluded from bulk-approve, never hard-blocked`);
    if (porcelain === null && ctx.git) notes.push('git status could not be read — secret remediation falls back to the non-git class');

    return makeStageResult({
      stage: triageStage.name,
      status: unreadable ? STATUS.PARTIAL : STATUS.OK,
      coverage: {
        scanned: verdicts.size - unreadable,
        skipped: unreadable,
        errored: 0,
        note: unreadable
          ? `${unreadable} path(s) could not be read in full by the gate — recorded as a coverage gap; any path-rule trigger on them still stands`
          : 'every in-scope path scanned in full (path rules + streaming content scan)',
      },
      findings,
      notes,
      data: { blocked: [...blocked], quarantined },
    });
  },
};

export default triageStage;

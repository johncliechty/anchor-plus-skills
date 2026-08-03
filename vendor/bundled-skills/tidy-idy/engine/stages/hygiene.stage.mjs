// engine/stages/hygiene.stage.mjs — Wave 1: hygiene demoted to REPORTING.
//
// Wave-0 inventory record (hygiene.mjs, kind=import-time-git): runHygieneCheck()
// hard-refused any non-git directory with a throw, and its library paths called
// process.exit(1) — killing the host process instead of returning a result. As
// a stage that behaviour is simply wrong: this is a READ-ONLY analysis pass
// that mutates nothing, so there is nothing for a refusal to protect, and a
// background run must never take the process down.
//
// So the stage REPORTS. It records repo presence, branch, head and dirty count
// into the envelope (Wave 2's dirty-tree policy: "scan is never blocked, dirty
// status is recorded"), and declares ctx.git === null as an ok/advisory state
// rather than an error. The legacy CLI's refusal is untouched — it still guards
// the LEGACY mutating path, which has no undo story at all. The engine's own
// path no longer needs it: Wave 4's reversible Trash (engine/apply/trash.mjs)
// supplies the non-git undo the refusal used to stand in for.

import { makeStageResult, STATUS } from '../envelope.mjs';

export const hygieneStage = {
  name: 'hygiene',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    findings: 0,
    note: 'no repo — git hygiene not applicable; run is advisory and mutates nothing',
  },

  async run(ctx) {
    if (!ctx.git) {
      ctx.state.gitSummary = null;
      return makeStageResult({
        stage: hygieneStage.name,
        status: STATUS.OK,
        coverage: { scanned: 0, skipped: 0, errored: 0, note: hygieneStage.gitNull.note },
        findings: [],
        notes: [
          'no git repository at the run root — this is a declared, supported state, not a failure',
          'analysis is read-only either way; removals for non-git-held content flow through the reversible Trash subsystem (Wave 4), never a destructive delete',
        ],
      });
    }

    const errors = [];
    let summary = null;
    try {
      summary = await ctx.git.summary();
    } catch (err) {
      errors.push({ message: `git status could not be read: ${err.message}` });
    }
    ctx.state.gitSummary = summary;

    const notes = [];
    if (summary) {
      notes.push(`branch=${summary.branch || '(detached)'} head=${summary.shortHead || '(unborn)'} dirty=${summary.dirtyCount}`);
      if (summary.dirty) {
        notes.push('working tree is DIRTY — recorded, not refused: the scan is read-only and the panel explains per-file Apply gating');
      }
    }
    if (ctx.git.rootIsToplevel === false) {
      notes.push(`run root is NOT the repository toplevel (${ctx.git.toplevel}) — Apply must refuse until they agree`);
    }

    return makeStageResult({
      stage: hygieneStage.name,
      status: errors.length ? STATUS.PARTIAL : STATUS.OK,
      coverage: { scanned: 1, skipped: 0, errored: errors.length },
      errors,
      findings: [],
      notes,
      data: { git: summary },
    });
  },
};

export default hygieneStage;

// engine/stages/analyze.stage.mjs — Wave 1: North-Star alignment as a stage(ctx).
//
// EXTEND, DON'T FORK: the batching + validation logic in bin/analyze.mjs is
// reused verbatim through runAnalysis(); this stage supplies everything that
// used to be coupled — the agent seam (ctx.agent, no hardcoded driver path) and
// the North-Star file (ctx.northStarFile) — and converts the result into the
// uniform envelope.
//
// Wave-0 record (analyze.mjs, foundry-marker-assumption): runAnalysis() threw
// 'No North Star file found' on a marker-less folder. Here that is a MODE
// question, not an exception: north-star mode runs the alignment analysis;
// heuristic and advisory modes return ok with zero findings and a coverage note
// naming exactly what did not run. Wave 2 fills heuristic mode in.
//
// A FAILED analysis is LOUD (status=failed with the error), never an empty
// finding list — the fake-clean failure mode this tool exists to not have.

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { runAnalysis } from '../../bin/analyze.mjs';
import { toPosixRel } from '../glob.mjs';

export const analyzeStage = {
  name: 'analyze',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // The declaration is a CAP on what a gitless run may emit. This stage's
    // findings do not depend on git at all, so a gitless run emits exactly what
    // a git-backed run would and git imposes no cap: the honest declared bound
    // is unbounded, not the zero a git-derived stage declares.
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — North-Star alignment analysis is content-only and does not consult git',
  },

  async run(ctx) {
    if (ctx.mode !== 'north-star') {
      return makeStageResult({
        stage: analyzeStage.name,
        status: STATUS.OK,
        coverage: {
          scanned: 0,
          skipped: 0,
          errored: 0,
          note: `mode=${ctx.mode}: North-Star alignment analysis does not apply (no North-Star document to align against); heuristic findings arrive in Wave 2`,
        },
        findings: [],
        notes: [`analysis skipped by MODE, not by failure — ${ctx.mode} mode has no North-Star document to judge alignment against`],
      });
    }

    // Wave 2: the UNIVERSAL PRE-LLM GATE. Secret-flagged content is excluded
    // where the prompt is assembled, not where the finding is emitted — by the
    // time a finding exists the bytes would already have been sent.
    const blocked = ctx.state.llmBlocked || new Set();
    const isAllowed = (abs) => !blocked.has(toPosixRel(path.relative(ctx.rootPath, abs)));

    let suspects;
    try {
      suspects = await runAnalysis(ctx.rootPath, {
        northStarFile: ctx.northStarFile,
        agent: ctx.agent,
        // The facade, not raw fs: Tier 1 of the tripwire must cover the whole
        // call tree a stage triggers, not merely the stage wrapper.
        fs: ctx.fs,
        log: ctx.log,
        isAllowed,
        throwOnError: true,
      });
    } catch (err) {
      // LOUD. The panel renders this as a failed stage; isClean is unreachable.
      return makeStageResult({
        stage: analyzeStage.name,
        status: STATUS.FAILED,
        coverage: { scanned: 0, skipped: (ctx.state.inScope || []).length, errored: 1, note: 'the analysis did NOT run — no clean verdict is derivable from this run' },
        errors: [{ name: err.name || 'Error', message: err.message }],
        findings: [],
      });
    }

    const findings = suspects.map((s) => ({
      stage: analyzeStage.name,
      kind: 'alignment-suspect',
      action: 'inspect',
      path: toPosixRel(path.relative(ctx.rootPath, s.filepath)),
      absolutePath: s.filepath,
      evidence: { reason: s.reason },
    }));
    ctx.state.suspects = suspects;

    return makeStageResult({
      stage: analyzeStage.name,
      status: STATUS.OK,
      coverage: { scanned: (ctx.state.inScope || []).length, skipped: 0, errored: 0 },
      findings,
      notes: [
        `${findings.length} alignment suspect(s) against ${path.basename(ctx.northStarFile || '')}`,
        `${blocked.size} secret-flagged path(s) were withheld from the analysis prompt by the pre-LLM gate — none of their bytes entered an LLM context`,
      ],
    });
  },
};

export default analyzeStage;

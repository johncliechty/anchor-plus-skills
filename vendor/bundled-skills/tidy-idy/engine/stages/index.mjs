// engine/stages/index.mjs — the stage registry.
//
// The orchestrator is a loop over THIS list. Adding a stage (save-detection in
// Wave 2, reorg in Wave 8) means adding an entry here — no orchestrator change,
// which is the "pluggable stages" property the later waves depend on.
//
// Every entry MUST declare `gitNull`: what the stage does when ctx.git is null.
// test/git-null-contract.test.mjs runs each stage against a gitless ctx and
// fails on ANY undeclared behaviour, so a stage cannot quietly acquire a git
// dependency later.
//
// ORDER IS PART OF THE CONTRACT, and one edge of it is a safety property rather
// than a convenience:
//
//   scan       — establishes the in-scope set (topology already ran)
//   hygiene    — records repo state; dirty is recorded, never a refusal
//   preflight  — non-git only: PROPOSES Bootstrap, writes nothing
//   triage     — THE UNIVERSAL PRE-LLM GATE. Everything below it consumes
//                gate-filtered input, and nothing above it sends content to a
//                model. Moving any LLM stage above this line reintroduces the
//                leak the gate exists to prevent.
//   save       — SAVE findings from git porcelain (secret-flagged paths excluded)
//   analyze    — North-Star alignment (LLM)
//   heuristic  — no-North-Star candidate evidence; feeds the re-scoped debate
//   debate     — attacker/judge (LLM), behind the removal-eligibility gate
//   compress   — in-memory content proposal (LLM)
//   reorg      — leaf/asset-directory move proposals + whole-tree reference scan
//                (filesystem-and-textual; no content reaches a model, so it may
//                sit after the LLM stages without reintroducing the gate leak)

import { scanStage } from './scan.stage.mjs';
import { hygieneStage } from './hygiene.stage.mjs';
import { preflightStage } from './preflight.stage.mjs';
import { triageStage } from './triage.stage.mjs';
import { saveStage } from './save.stage.mjs';
import { analyzeStage } from './analyze.stage.mjs';
import { heuristicStage } from './heuristic.stage.mjs';
import { debateStage } from './debate.stage.mjs';
import { compressStage } from './compress.stage.mjs';
import { reorgStage } from './reorg.stage.mjs';

export const STAGES = Object.freeze([
  scanStage,
  hygieneStage,
  preflightStage,
  triageStage,
  saveStage,
  analyzeStage,
  heuristicStage,
  debateStage,
  compressStage,
  reorgStage,
]);

/** Stages that put file content in front of a model. All must sit after triage. */
export const LLM_STAGES = Object.freeze(['analyze', 'debate', 'compress']);

/** The gate every LLM stage must sit behind. Asserted by the Wave-2 suite. */
export const PRE_LLM_GATE_STAGE = 'triage';

export {
  scanStage, hygieneStage, preflightStage, triageStage, saveStage,
  analyzeStage, heuristicStage, debateStage, compressStage, reorgStage,
};
export default STAGES;

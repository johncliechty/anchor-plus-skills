// bin/matrix-planner.mjs — Wave 5: the deterministic Gate-2 plan-matrix artifact.
//
// The plan the human approves at Gate 2 is a PURE function of the locked objective —
// no clock, no randomness, no host state — so the same objective always serializes
// to the same bytes and therefore the same planHash. Replay-bound approval fixtures
// (Wave 8) and the EDIT-cycle re-hash discipline (Wave 5) both depend on this.
import crypto from 'node:crypto';

export const PLAN_VERSION = 1;

/**
 * Build the deterministic research plan matrix for an objective.
 *
 * @param {{objective: string}} params
 * @returns {{planVersion:number, objective:string, objectiveHash:string,
 *   matrix:Array<{stage:string, gate:string, task:string}>}}
 */
export function planMatrix({ objective } = {}) {
  if (typeof objective !== 'string' || objective.length === 0) {
    throw new TypeError('planMatrix requires a non-empty objective string');
  }
  const objectiveHash = crypto.createHash('sha256').update(objective, 'utf8').digest('hex');
  return {
    planVersion: PLAN_VERSION,
    objective,
    objectiveHash,
    matrix: [
      { stage: 'scope', gate: 'gate1', task: `Bound what is in and out of scope for: ${objective}` },
      { stage: 'evidence', gate: 'rounds', task: `Gather the sources and probes that bear on: ${objective}` },
      { stage: 'adversarial', gate: 'rounds', task: `Attempt to refute the leading answer to: ${objective}` },
      { stage: 'synthesis', gate: 'gate2', task: `Assemble the deliverable that answers: ${objective}` },
    ],
  };
}

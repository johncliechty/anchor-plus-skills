// bin/phase1.mjs — Wave 4 Phase-1 seam: run the stakes adjudication + Oranges foresight and emit
// ONE persisted Phase-1 receipt (IMPLEMENTATION-PLAN Wave 4 done-when: "Phase-1 emits a persisted
// stakes vector → governor tier, and an Oranges receipt").
//
// This is the seam the engine (Wave 5+) calls before the verification loop: it adjudicates the
// declared stakes into a governor tier (which scales the loop) and runs foresight to re-aim the
// research plan, then PERSISTS both as a single durable receipt so the run is replayable and
// reviewer-checkable. Persistence is additive: the receipt embeds the RAW declared stakes vector
// verbatim (`receipt.stakes.raw`), so a consumer that only knows the declared axes still reads them
// after the round-trip — no schema break.
//
// The write is atomic (temp file + rename) so a crash mid-write can never leave a torn receipt —
// the same durability discipline the trio's checkpointing uses. The module is otherwise pure:
// `runPhase1` is a deterministic function of its input.

import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { adjudicateStakes } from './stakes.mjs';
import { runForesight } from './oranges.mjs';

export const PHASE1_SCHEMA_VERSION = 1;

/**
 * Run the Phase-1 seam over one item.
 * @param {{ stakes: object, plan: {branches:object[]} }} item
 *   - `stakes`: the declared stakes vector (see bin/stakes.mjs adjudicateStakes).
 *   - `plan`:   the research plan to re-aim (see bin/oranges.mjs runForesight).
 * @returns {{ schema_version:number, tier:string, stakes:object, foresight:object }}
 */
export function runPhase1(item) {
  if (!item || typeof item !== 'object') {
    throw new TypeError('runPhase1 requires an item { stakes, plan }');
  }
  const stakes = adjudicateStakes(item.stakes ?? {});
  const foresight = runForesight(item.plan ?? { branches: [] });
  return {
    schema_version: PHASE1_SCHEMA_VERSION,
    tier: stakes.tier, // the governor tier the loop scales by (projection of the stakes vector)
    stakes, // carries `raw` (the verbatim declared vector) + axis_tiers + overrides
    foresight, // the Oranges receipt (dropped/reordered + stamp + crit3_satisfied)
  };
}

/**
 * Persist a Phase-1 receipt durably (atomic temp-file + rename).
 * @param {object} receipt a value from runPhase1
 * @param {URL|string} file destination
 */
export function persistPhase1(receipt, file) {
  const dest = file instanceof URL ? fileURLToPath(file) : file;
  const tmp = `${dest}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(receipt, null, 2) + '\n');
  fs.renameSync(tmp, dest); // atomic publish — readers never see a torn file
}

/**
 * Load a persisted Phase-1 receipt.
 * @param {URL|string} file
 * @returns {object} the parsed receipt
 */
export function loadPhase1(file) {
  const src = file instanceof URL ? fileURLToPath(file) : file;
  return JSON.parse(fs.readFileSync(src, 'utf8'));
}

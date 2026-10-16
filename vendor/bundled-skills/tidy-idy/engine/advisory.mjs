// engine/advisory.mjs — Wave 2: honest labelling for ordinary-folder runs.
//
// Two labels, applied to findings after protection has filtered them, so the
// panel never has to infer anything about the run it is rendering:
//
//   ADVISORY (no repository). Amendment A relaxed what this means. It no longer
//     says "we refuse to act here" — a non-git folder's removals flow through
//     the reversible Trash, so the honest marker names the APPLY PATH and the
//     UNDO, and adds that `git init` is an optional upgrade rather than a gate.
//     A marker that still said "removals are refused without git" would now be
//     a lie about the tool's own behaviour.
//
//   HEURISTIC CANDIDATE (no North-Star document). The evidence for these
//     findings is a file's age or its duplicate hash, not an argued relationship
//     to a stated objective — so they are labelled as such, carry their raw
//     evidence, and DEFAULT TO UNCHECKED. Default-checked heuristics would make
//     bulk-approve mean "delete whatever looked old", which is the opposite of
//     the tool's premise.

/** Findings that would change the tree if approved. */
const ACTIONABLE = new Set(['remove', 'move', 'reorg', 'trash', 'save']);

/**
 * Stamp the run-level advisory marker onto findings. Idempotent.
 *
 * @param {object[]} findings
 * @param {{git: object|null, mode: string}} ctx
 */
export function markAdvisory(findings, ctx) {
  if (ctx.git) return 0;
  let marked = 0;
  for (const f of findings || []) {
    if (!f || !ACTIONABLE.has(f.action)) continue;
    const isSave = f.action === 'save';
    const isMove = f.action === 'move' || f.action === 'reorg';
    f.advisory = {
      reason: 'no git repository at the run root',
      // A reorg/move without a repo does NOT go to the Trash — it moves to its new
      // path through the journaled move-set, undone by a journaled move-back
      // (engine/apply/reorg.mjs). Saying "trash" here would be a lie about the
      // tool's own behaviour, the exact failure mode this marker exists against.
      applyPath: isSave ? 'bootstrap-first' : isMove ? 'journaled-move-set' : 'trash',
      undo: isSave
        ? 'nothing to commit to yet — a SAVE needs a repository, so Bootstrap (optional, proposed by the preflight) has to happen first'
        : isMove
          ? 'journaled move-back — the file is MOVED to its new path (never the Trash, never deleted); undo restores it to its original path'
          : 'restore-from-Trash — the file is MOVED into .tidy-idy/trash/<run-id>/, never deleted (Amendment A)',
      note: '`git init` is an optional upgrade here, not a gate: removals and moves are reversible without it',
    };
    marked++;
  }
  return marked;
}

/**
 * Stamp the heuristic-mode marker. Applied by the heuristic stage itself at
 * emission (so the label and the evidence are produced together) and re-applied
 * here for any finding that reached the envelope from another stage in a
 * heuristic-mode run.
 *
 * @param {object[]} findings
 * @param {{mode: string}} ctx
 */
export function markHeuristic(findings, ctx) {
  if (ctx.mode !== 'heuristic') return 0;
  let marked = 0;
  for (const f of findings || []) {
    if (!f || !ACTIONABLE.has(f.action)) continue;
    if (f.label === undefined) f.label = 'heuristic candidate';
    if (f.defaultChecked === undefined) f.defaultChecked = false;
    if (!f.evidenceNote) {
      f.evidenceNote = 'no North-Star document exists for this folder, so this finding rests on raw file evidence (age / duplicate hash / references / git status) rather than on an argued relationship to a stated objective — review the evidence before approving';
    }
    marked++;
  }
  return marked;
}

export default { markAdvisory, markHeuristic };

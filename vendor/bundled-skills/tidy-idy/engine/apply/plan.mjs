// engine/apply/plan.mjs — Wave 3: approved findings → one ordered operation set.
//
// This module turns tiles into operations and then REFUSES to be creative. Two
// rules it exists to enforce:
//
//   ONE FINDING, ONE OPERATION, NO EXTRAS (the CONSENT-SCOPE INVARIANT). An
//     approved operation mutates only the state its tile named. Every op
//     therefore carries `declaredTransitions` — the exact per-path git tracking
//     class changes the tile disclosed — and engine/apply/consent-scope.mjs
//     later asserts that the Apply produced NO class change that no tile
//     declared. Ignore-rule and index-class writes are their own approvable
//     findings; they are never a side effect of a REMOVE or a SAVE.
//
//   AN OPERATION WE CANNOT COMPILE IS A REFUSAL, NOT A SKIP. An approved tile
//     that quietly does nothing is the worst outcome available: the human
//     believes the thing happened. Unsupported kinds abort the whole Apply.
//
// ORDERING. The canonical pipeline requires "mkdir before move-in, moves before
// deletes-at-old-paths". In temp-index space there are no directories to create
// (a tree is implied by its entries), so what survives of that requirement is
// the ordering between classes: MOVES first (each internally add-then-remove),
// then content writes, then removals. Within a class the order is by path, so a
// compiled plan is deterministic and diffable across runs.

import { toPosixRel } from '../glob.mjs';

/** The operation kinds this executor knows how to compile. */
export const OP_KIND = Object.freeze({
  REMOVE: 'remove-tracked',
  SAVE: 'save-blob',
  MOVE: 'move-tracked',
  WRITE: 'write-blob',
  GITIGNORE: 'add-to-gitignore',
  TRASH: 'trash-move',
});

/** Class ordering; lower runs first. */
const ORDER = {
  [OP_KIND.MOVE]: 0,
  [OP_KIND.WRITE]: 1,
  [OP_KIND.SAVE]: 1,
  [OP_KIND.GITIGNORE]: 2,
  [OP_KIND.REMOVE]: 3,
  [OP_KIND.TRASH]: 4,
};

/** The section a finding's operation is reported under in the commit message. */
const SECTION = {
  [OP_KIND.REMOVE]: 'removals',
  [OP_KIND.TRASH]: 'removals (trash)',
  [OP_KIND.SAVE]: 'saves',
  [OP_KIND.WRITE]: 'content proposals',
  [OP_KIND.GITIGNORE]: 'ignore rules',
  [OP_KIND.MOVE]: 'reorganisations',
};

/**
 * Compile approved findings into ordered operations.
 *
 * @param {{findings: object[], runId: string}} opts
 * @returns {{ops: object[], unsupported: object[]}}
 */
export function planFromFindings({ findings = [], runId } = {}) {
  const ops = [];
  const unsupported = [];

  for (const f of findings) {
    const rel = toPosixRel(f.path);
    const base = { id: f.id || null, findingKind: f.kind || null, action: f.action, path: rel, finding: f };

    switch (f.action) {
      case 'remove':
        ops.push({
          ...base,
          kind: OP_KIND.REMOVE,
          declaredTransitions: [{ path: rel, from: f.trackingClass || 'tracked-clean', to: 'absent', declaredBy: f.id || null }],
          summary: `remove ${rel} (git holds the content; undo = git revert)`,
        });
        break;

      case 'trash':
        // Amendment A's reversible Trash (engine/apply/trash.mjs). Compiled into
        // the same ordered plan as the git ops so both halves of one Apply are
        // approved, revalidated and ordered together — but realised outside the
        // temp index, because git holds none of this content.
        ops.push({
          ...base,
          kind: OP_KIND.TRASH,
          declaredTransitions: [{ path: rel, from: f.trackingClass || 'untracked', to: 'absent', declaredBy: f.id || null }],
          summary: `move ${rel} into the reversible Trash (git does not hold this content)`,
        });
        break;

      case 'save':
        ops.push({
          ...base,
          kind: OP_KIND.SAVE,
          // The bytes are read from the working tree AT COMPILE TIME, under the
          // lock, only after revalidation proved they still hash to what the
          // tile described.
          readFromWorkingTree: true,
          declaredTransitions: [{ path: rel, from: f.trackingClass || 'untracked', to: 'tracked-clean', declaredBy: f.id || null }],
          summary: `commit the current content of ${rel}`,
        });
        break;

      case 'propose-content': {
        const content = f.proposal ? f.proposal.content : null;
        if (typeof content !== 'string' && !Buffer.isBuffer(content)) {
          unsupported.push({ id: f.id || null, path: rel, action: f.action, reason: 'a content proposal must carry the exact approved bytes on the finding; there is no re-read from the working tree (Amendment C.iv)' });
          break;
        }
        ops.push({
          ...base,
          kind: OP_KIND.WRITE,
          content: Buffer.isBuffer(content) ? content : Buffer.from(content, 'utf8'),
          declaredTransitions: [{ path: rel, from: f.trackingClass || (f.proposal.createsFile ? 'absent' : 'tracked-clean'), to: 'tracked-clean', declaredBy: f.id || null }],
          summary: `write the approved content of ${rel} (hashed from memory, never re-read from disk)`,
        });
        break;
      }

      case 'add-to-gitignore': {
        const line = f.gitignoreLine || rel;
        ops.push({
          ...base,
          kind: OP_KIND.GITIGNORE,
          gitignoreLine: String(line),
          // The ONLY op allowed to touch .gitignore, and it exists solely as its
          // own explicitly-approved finding.
          declaredTransitions: [
            { path: '.gitignore', from: '*', to: 'tracked-clean', declaredBy: f.id || null },
            { path: rel, from: f.trackingClass || 'untracked', to: 'ignored', declaredBy: f.id || null },
          ],
          summary: `add \`${line}\` to .gitignore`,
        });
        break;
      }

      case 'move':
      case 'reorg': {
        const from = toPosixRel((f.move && f.move.from) || f.from || rel);
        const to = toPosixRel((f.move && f.move.to) || f.to || '');
        if (!to) {
          unsupported.push({ id: f.id || null, path: rel, action: f.action, reason: 'a move finding must name its destination' });
          break;
        }
        ops.push({
          ...base,
          kind: OP_KIND.MOVE,
          from,
          to,
          declaredTransitions: [
            { path: from, from: f.trackingClass || 'tracked-clean', to: 'absent', declaredBy: f.id || null },
            { path: to, from: 'absent', to: 'tracked-clean', declaredBy: f.id || null },
          ],
          summary: `move ${from} → ${to}`,
        });
        break;
      }

      default:
        unsupported.push({
          id: f.id || null,
          path: rel,
          action: f.action,
          reason: `action '${f.action}' has no compiled operation in this executor — an approved tile that silently does nothing is worse than a refusal, so the whole Apply aborts`,
        });
    }
  }

  return { ops: orderOps(ops), unsupported };
}

/** Deterministic topological order: moves, then writes/saves, then removals. */
export function orderOps(ops) {
  return [...ops].sort((a, b) => {
    const d = (ORDER[a.kind] ?? 99) - (ORDER[b.kind] ?? 99);
    if (d !== 0) return d;
    return String(a.path).localeCompare(String(b.path));
  });
}

/** Every path an op would touch — the pathspec set for step-5 realization. */
export function opPaths(op) {
  if (op.kind === OP_KIND.MOVE) return [op.from, op.to];
  if (op.kind === OP_KIND.GITIGNORE) return ['.gitignore'];
  return [op.path];
}

/** All class transitions the approved tiles declared, flattened. */
export function declaredTransitions(ops) {
  return ops.flatMap((op) => op.declaredTransitions || []);
}

/**
 * The case-collision refusal (`core.ignorecase`). On a case-insensitive
 * filesystem two paths differing only in case are ONE file, so a plan
 * containing both would have git and the filesystem disagree about what exists —
 * and the loser is whichever content got written second. v1 refuses instead.
 */
export function findCaseCollisions({ ops, existingPaths = [], ignorecase = false }) {
  if (!ignorecase) return [];
  const collisions = [];
  const seen = new Map();

  const consider = (p, source) => {
    const key = p.toLowerCase();
    const prior = seen.get(key);
    if (prior && prior.path !== p) collisions.push({ a: prior.path, b: p, reason: `\`${prior.path}\` and \`${p}\` differ only in case and core.ignorecase is true — they are the same file on this filesystem`, source });
    else if (!prior) seen.set(key, { path: p, source });
  };

  for (const p of existingPaths) consider(p, 'working tree');
  for (const op of ops) for (const p of opPaths(op)) consider(p, `op ${op.kind}`);

  return collisions;
}

/**
 * The commit message: human-readable sections plus ONE machine-readable trailer.
 *
 * The trailer matters more than it looks. Undo needs to know which paths in the
 * commit were SAVEs (they get the decision-#8 compensation) and which were
 * REMOVEs or MOVEs (pure revert). Carrying that in the commit itself means an
 * undo still works correctly after `.tidy-idy/` has been deleted, which is
 * exactly the kind of directory people delete.
 */
export const PLAN_TRAILER = 'tidy-idy-plan-v1:';

export function buildCommitMessage({ runId, ops, rulesetVersion = null }) {
  const bySection = new Map();
  for (const op of ops) {
    const section = SECTION[op.kind] || 'operations';
    if (!bySection.has(section)) bySection.set(section, []);
    bySection.get(section).push(op);
  }

  const lines = [
    `tidy-idy: ${ops.length} approved operation(s) in one commit [run ${runId}]`,
    '',
  ];
  for (const [section, list] of bySection) {
    lines.push(`${section} (${list.length}):`);
    for (const op of list) lines.push(`  - ${op.id || '(no id)'} ${op.kind === OP_KIND.MOVE ? `${op.from} → ${op.to}` : op.path}`);
    lines.push('');
  }
  lines.push('Every operation above was individually approved by a human against a rendered tile.');
  lines.push('Undo: `git revert` this commit (SAVE paths additionally get their pre-Apply working-tree content re-materialised unstaged).');
  lines.push('');
  if (rulesetVersion) lines.push(`ruleset: ${rulesetVersion}`);
  lines.push(`${PLAN_TRAILER} ${JSON.stringify({
    runId,
    ops: ops.map((op) => ({
      id: op.id,
      kind: op.kind,
      action: op.action,
      path: op.path,
      ...(op.from ? { from: op.from } : {}),
      ...(op.to ? { to: op.to } : {}),
    })),
  })}`);

  return lines.join('\n');
}

/** Recover the compiled plan from a commit message trailer. */
export function parsePlanTrailer(message) {
  for (const line of String(message).split('\n')) {
    const i = line.indexOf(PLAN_TRAILER);
    if (i === -1) continue;
    try {
      return JSON.parse(line.slice(i + PLAN_TRAILER.length).trim());
    } catch {
      return null;
    }
  }
  return null;
}

export default { planFromFindings, orderOps, opPaths, declaredTransitions, findCaseCollisions, buildCommitMessage, parsePlanTrailer, OP_KIND };

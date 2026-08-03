// engine/launch/identity.mjs — Wave 5: folder-agnostic project identity.
//
// The panel header has to be able to say WHICH project it is looking at, and the
// archive has to be able to say which project it belongs to. Under the Phase-5
// framing that answer came from Anchor's project registry, which quietly made a
// registry lookup a PRECONDITION of running the tool at all — and Amendment D
// makes the tool standalone on ANY folder, including one Anchor has never heard
// of.
//
// So identity is DERIVED FROM THE FOLDER and from nothing else:
//
//   name        the folder's own basename
//   path        its absolute, resolved path
//   git         present/absent, and when present: branch, head, short sha,
//               dirty count — read from the run's own git handle
//
// There is no registry read on this path, no Anchor import, and no branch that
// behaves differently when Anchor happens to be running. An Anchor project id,
// when one exists, is carried as an ANNOTATION (`anchor.projectId`) supplied by
// the caller — never consulted to decide what the project IS.

import path from 'node:path';

/**
 * Derive a run's project identity.
 *
 * @param {{rootPath: string, git?: object|null, gitSummary?: object|null,
 *          anchor?: {projectId?: string|null, dispatched?: boolean}|null}} opts
 * @returns {{name: string, path: string, git: object, anchor: object, label: string}}
 */
export function projectIdentity({ rootPath = '.', git = null, gitSummary = null, anchor = null } = {}) {
  // No target given → the current directory, derived explicitly (never an
  // accident of the launch CWD leaking through an unresolvable undefined).
  const abs = path.resolve(rootPath ?? '.');
  const name = path.basename(abs) || abs;

  const head = git ? git.head || null : null;
  const gitPart = git
    ? {
      present: true,
      toplevel: git.toplevel || abs,
      rootIsToplevel: Boolean(git.rootIsToplevel),
      branch: (gitSummary && gitSummary.branch) || git.branch || null,
      head,
      shortSha: head ? head.slice(0, 7) : null,
      dirtyCount: gitSummary && Number.isInteger(gitSummary.dirtyCount) ? gitSummary.dirtyCount : null,
      dirty: gitSummary ? Boolean(gitSummary.dirty) : null,
    }
    : {
      present: false,
      toplevel: null,
      rootIsToplevel: null,
      branch: null,
      head: null,
      shortSha: null,
      dirtyCount: null,
      dirty: null,
      note: 'no repository at this root — removals apply through the reversible Trash (Amendment A); Bootstrap is an optional upgrade, never a gate',
    };

  return {
    name,
    path: abs,
    git: gitPart,
    /**
     * Anchor annotation ONLY. Never load-bearing: a standalone run leaves it
     * absent, and no behaviour in this tool reads it to decide what to do.
     */
    anchor: {
      projectId: (anchor && anchor.projectId) || null,
      dispatched: Boolean(anchor && anchor.dispatched),
      note: 'annotation only — project identity is derived from the folder, never from an Anchor registry',
    },
    label: formatIdentity({ name, path: abs, git: gitPart }),
  };
}

/** The one-line header string a panel/CLI prints. Same text on every path. */
export function formatIdentity({ name, path: abs, git }) {
  if (!git || !git.present) return `${name} — ${abs} — no git repository`;
  const bits = [git.branch || 'detached'];
  if (git.shortSha) bits.push(git.shortSha);
  if (Number.isInteger(git.dirtyCount)) bits.push(git.dirtyCount ? `${git.dirtyCount} dirty` : 'clean tree');
  return `${name} — ${abs} — git: ${bits.join(' @ ')}`;
}

/**
 * Two identities describe the same project when their resolved paths match.
 * Used by the parity test and by the panel's "a newer run superseded this one"
 * check — deliberately path equality, not name equality, because two folders
 * called `src` are not one project.
 */
export function sameProject(a, b) {
  if (!a || !b) return false;
  return path.resolve(a.path) === path.resolve(b.path);
}

export default { projectIdentity, formatIdentity, sameProject };

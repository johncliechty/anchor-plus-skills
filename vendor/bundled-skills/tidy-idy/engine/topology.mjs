// engine/topology.mjs — Wave 1: the run-start topology check.
//
// Before any stage runs we establish exactly WHAT TREE we are allowed to look
// at, because "the project root" is not a simple idea on a real filesystem:
//
//   • the root may sit inside an ENCLOSING repository (then a git mutation
//     pinned to the wrong toplevel would touch someone else's history);
//   • the tree may contain NESTED repositories or SUBMODULES (whose contents
//     belong to another history entirely — hard-filtered, never scanned);
//   • it may contain SYMLINKS that resolve outside the root (Amendment C.ii:
//     recorded as link OBJECTS, never followed for read or SAVE — following one
//     would let a finding, and later an Apply, reach outside the project);
//   • it may contain a DIRECTORY JUNCTION escaping the root, which on Windows is
//     indistinguishable from a real subdirectory to a naive walk and would
//     silently pull an arbitrary tree into scope — that ABORTS the run.
//
// The excluded subtree list is recorded in the envelope, so a run can always
// say what it did NOT look at instead of quietly reporting a partial tree as
// the whole thing.

import fsp from 'node:fs/promises';
import path from 'node:path';
import { toPosixRel } from './glob.mjs';

export const TOPOLOGY_STATUS = Object.freeze({ OK: 'ok', PARTIAL: 'partial', ABORTED: 'aborted' });

function isInside(parent, child) {
  const rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/**
 * @param {{rootPath: string, git?: object|null, fs?: object, isExcluded?: Function, reportDir?: string|null}} opts
 * @returns {Promise<{status: string, toplevel: string|null, rootIsToplevel: boolean|null,
 *   excludedSubtrees: object[], links: object[], errors: object[], aborted: boolean, abortReason: string|null}>}
 */
export async function checkTopology({ rootPath, git = null, fs = fsp, isExcluded = () => false, reportDir = null }) {
  const root = path.resolve(rootPath);
  const result = {
    status: TOPOLOGY_STATUS.OK,
    root,
    toplevel: null,
    rootIsToplevel: null,
    excludedSubtrees: [],
    links: [],
    errors: [],
    aborted: false,
    abortReason: null,
  };

  // 1. Toplevel resolution. A root that is not its repo's toplevel is not an
  //    abort (analysis is read-only), but it IS recorded — Wave 3 pins every
  //    mutation to the root and asserts this equality before it writes.
  if (git) {
    result.toplevel = git.toplevel || null;
    result.rootIsToplevel = Boolean(git.rootIsToplevel);
    if (!git.rootIsToplevel) {
      result.status = TOPOLOGY_STATUS.PARTIAL;
      result.errors.push({
        kind: 'enclosing-repo',
        message: `the run root '${root}' is not its repository's toplevel ('${git.toplevel}') — analysis proceeds read-only, and Apply must refuse until the root and toplevel agree`,
      });
    }
  }

  // 2. Submodule declarations (hard-filtered before the walk so we never even
  //    read a submodule's contents).
  const declaredSubmodules = new Set();
  try {
    const text = await fs.readFile(path.join(root, '.gitmodules'), 'utf8');
    for (const m of String(text).matchAll(/^\s*path\s*=\s*(.+)$/gm)) {
      declaredSubmodules.add(toPosixRel(m[1].trim()));
    }
  } catch { /* no .gitmodules is the common case */ }

  const excluded = [];
  const addExclusion = (rel, reason, detail) => {
    excluded.push({ path: toPosixRel(rel), reason, ...(detail ? { detail } : {}) });
  };

  // 3. The walk. Returns the in-scope FILE list as a side product so the scan
  //    stage and snapshot S share exactly one enumeration.
  const inScope = [];

  async function walk(dirAbs) {
    let entries;
    try {
      entries = await fs.readdir(dirAbs, { withFileTypes: true });
    } catch (err) {
      result.errors.push({ kind: 'unreadable-dir', path: toPosixRel(path.relative(root, dirAbs)), message: err && err.message });
      return;
    }

    for (const entry of entries) {
      const abs = path.join(dirAbs, entry.name);
      const rel = toPosixRel(path.relative(root, abs));
      if (!rel) continue;

      // reportDir is the run's own output location: never scanned, never in S.
      if (reportDir && isInside(path.resolve(reportDir), abs)) {
        addExclusion(rel, 'report-dir', "the run's own reportDir is excluded from scan and from the tripwire");
        continue;
      }

      // Links first — an entry can be a symlink AND look like a directory.
      if (entry.isSymbolicLink()) {
        const link = await classifyLink({ abs, rel, root, fs });
        result.links.push(link);
        if (link.escapes && link.targetKind === 'directory') {
          // A directory link escaping the root would splice a foreign tree into
          // scope. There is no safe read-only reading of that; abort.
          result.aborted = true;
          result.status = TOPOLOGY_STATUS.ABORTED;
          result.abortReason =
            `directory junction/symlink '${rel}' resolves to '${link.target}', outside the run root '${root}' — ` +
            'a junction escaping the root would pull an arbitrary tree into scope; the run is aborted rather than scanning outside the project';
          return;
        }
        // Escaping FILE links: recorded as link objects, never followed for
        // read or SAVE (Amendment C.ii). Non-escaping links are equally not
        // followed — the real path is already in scope on its own.
        addExclusion(rel, link.escapes ? 'symlink-escapes-root' : 'symlink', `link object recorded, never followed (target: ${link.target || 'unresolvable'})`);
        continue;
      }

      if (entry.isDirectory()) {
        if (declaredSubmodules.has(rel)) {
          addExclusion(rel, 'submodule', 'declared in .gitmodules — contents belong to another history');
          continue;
        }
        // A nested repository (dir OR gitlink file) is another project.
        let nested = false;
        try {
          await fs.stat(path.join(abs, '.git'));
          nested = true;
        } catch { /* not nested */ }
        if (nested) {
          addExclusion(rel, 'nested-repo', 'contains its own .git — hard-filtered from scan, snapshot and findings');
          continue;
        }
        if (isExcluded(rel)) {
          addExclusion(rel, 'exclusion-set', 'matched the run exclusion set');
          continue;
        }
        await walk(abs);
        if (result.aborted) return;
        continue;
      }

      if (entry.isFile()) {
        if (isExcluded(rel)) { addExclusion(rel, 'exclusion-set', 'matched the run exclusion set'); continue; }
        inScope.push(rel);
      }
      // Sockets/FIFOs/devices are neither scanned nor an error.
    }
  }

  // The root's own .git is excluded up front (it is repository metadata, not
  // project content) so the walk never descends into it.
  addExclusion('.git', 'repo-metadata', "the root repository's own .git directory");
  await walk(root);

  result.excludedSubtrees = excluded;
  result.inScope = inScope.sort();
  if (!result.aborted && result.errors.length && result.status === TOPOLOGY_STATUS.OK) {
    result.status = TOPOLOGY_STATUS.PARTIAL;
  }
  return result;
}

async function classifyLink({ abs, rel, root, fs }) {
  let target = null;
  let resolved = null;
  let targetKind = 'unknown';
  try {
    target = await fs.readlink(abs);
  } catch { /* unresolvable link: still recorded */ }
  if (target) {
    resolved = path.isAbsolute(target) ? path.resolve(target) : path.resolve(path.dirname(abs), target);
    try {
      const st = await fs.stat(abs); // follows the link — metadata only, never content
      targetKind = st.isDirectory() ? 'directory' : (st.isFile() ? 'file' : 'other');
    } catch {
      targetKind = 'broken';
    }
  }
  return {
    path: rel,
    kind: 'link',
    target: resolved || target,
    targetKind,
    escapes: Boolean(resolved && !isInside(root, resolved)),
    followed: false,
    note: 'link objects are recorded, never followed for read or SAVE (Amendment C.ii)',
  };
}

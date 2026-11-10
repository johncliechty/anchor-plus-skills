// preflight.mjs — S2 of the slim plan (2026-10-10): which repos the plan really names, and which named inputs are
// missing. Pure over injected filesystem/git probes, so it is unit-tested without a live run.
//
// Before, every absolute path in the plan climbed to its nearest `.git` with no boundary. <path> is itself a repo, so
// any <path> path not inside its own repo - or the job's own checkout - resolved to a CONTAINER repo that is always
// dirty, and the run HALTed before it began (5 of the historical "did not finish, exit 3"; <path> 240 paths,
// <path> 38, AppData\Local 56). Now a repo is a sibling to guard only when it is not:
//   - the project, an ancestor of the project, or the engine's own home (or an ancestor of it);
//   - the same repository as the project (another worktree of the project's own git common dir);
//   - a container of the user's home (the home, AppData, AppData\Local, AppData\Roaming, a drive root).
// And a plan's "Inputs" section is a contract: a path listed there that does not exist stops the run before it
// starts ([taxonomy:input-unreachable]) instead of failing mid-wave with a BLOCKED seat (c5594f). A path named
// elsewhere in the plan may be an output still to be made, so it only earns a note, as before.

import path from 'node:path';

// An absolute path: a drive (C:\ or C:/) or a UNC share (\\server\share). Quoted spans are matched by their OWN
// delimiter, so "C:\data\O'Brien.csv" and `C:\data\results (final)` keep every character (review r1).
const ABS = String.raw`(?:[A-Za-z]:[\\/]|\\\\[^\\/\s"'` + '`' + String.raw`]+[\\/])`;
const QUOTED = new RegExp(String.raw`"(${ABS}[^"\r\n]*)"|'(${ABS}[^'\r\n]*)'|` + '`' + `(${ABS}[^` + '`' + String.raw`\r\n]*)` + '`', 'g');
const BARE = new RegExp(String.raw`${ABS}(?:[^\s"'` + '`' + String.raw`|<>*?\r\n]+)`, 'g');

/** Absolute paths named in a text: quoted spans exactly as written (they may hold spaces), then bare tokens found
 * OUTSIDE the quoted spans, with trailing prose punctuation trimmed. */
export function planPathTokens(text) {
  const out = [];
  const seen = new Set();
  const add = (p) => {
    const k = p.toLowerCase();
    if (p && !seen.has(k)) { seen.add(k); out.push(p); }
  };
  const src = String(text || '');
  for (const m of src.matchAll(QUOTED)) add(m[1] ?? m[2] ?? m[3]);
  const rest = src.replace(QUOTED, (m) => ' '.repeat(m.length));     // a quoted span is never re-read as bare
  for (const m of rest.match(BARE) ?? []) add(m.replace(/[),.;:\]]+$/, ''));
  return out;
}

/** The paths an Inputs section lists: absolute ones as written, and a list item's relative path (`data/x.csv`,
 * "./in/y.json") resolved against the project. */
export function inputPaths(section, projReal) {
  const out = planPathTokens(section);
  for (const line of String(section || '').split(/\r?\n/)) {
    const item = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (!item) continue;
    // each quote closes with its OWN delimiter: `data/O'Brien.csv` stays whole (review r1)
    const q = /^(?:"([^"\r\n]+)"|'([^'\r\n]+)'|`([^`\r\n]+)`)/.exec(item[1].trim());
    const tok = q ? (q[1] ?? q[2] ?? q[3]) : item[1].trim().split(/\s+/)[0];
    if (!tok || new RegExp('^' + ABS).test(tok) || /^[a-z]+:\/\//i.test(tok)) continue;
    // only an unmistakable path: quoted, or holding a separator ("v1.2" or "e.g." in prose is never an input)
    if (q || /[\\/]/.test(tok)) out.push(path.resolve(projReal, tok));
  }
  return out;
}

/** The text of the plan's Inputs section(s): a heading whose words are "inputs" / "normative inputs" / "input
 * files", up to the next heading of the same or a higher level. '' when the plan has none. */
export function inputsSection(text) {
  const lines = String(text || '').split(/\r?\n/);
  const out = [];
  let level = 0;
  for (const line of lines) {
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      if (level && h[1].length <= level) level = 0;
      if (/^(normative\s+)?inputs?(\s+files?)?\b/i.test(h[2].trim())) { level = h[1].length; continue; }
    }
    if (level) out.push(line);
  }
  return out.join('\n');
}

const norm = (p) => path.resolve(p).replace(/[\\/]+$/, '').toLowerCase();
const isWithin = (child, parent) => {
  const c = norm(child), p = norm(parent);
  return c === p || c.startsWith(p + path.sep.toLowerCase()) || c.startsWith(p + '/');
};

/** Containers of the user's own files: never a "sibling repo", whatever .git they hold. */
export function containerDirs(home) {
  if (!home) return [];
  return [home, path.join(home, 'AppData'), path.join(home, 'AppData', 'Local'), path.join(home, 'AppData', 'Roaming')];
}

/**
 * The sibling-repo plan. Probes (injected): exists(p) -> 'dir'|'file'|null; gitRootOf(dir) -> realpath|null;
 * commonDirOf(repo) -> the repo's git common dir (realpath) or null.
 * Returns { checked: [repo], excluded: [{repo, why}], unresolved: [path], missingInputs: [path] }.
 */
export function siblingPlan({ planText, projReal, engineHome = null, home = null, exists, gitRootOf, commonDirOf = () => null }) {
  const checked = [];
  const excluded = [];
  const unresolved = [];
  const roots = new Map();
  for (const p of planPathTokens(planText)) {
    const kind = exists(p);
    if (!kind) { unresolved.push(p); continue; }
    const root = gitRootOf(kind === 'dir' ? p : path.dirname(p));
    if (root && !roots.has(norm(root))) roots.set(norm(root), root);
  }
  const projCommon = commonDirOf(projReal);
  const containers = containerDirs(home).map(norm);
  for (const root of roots.values()) {
    let why = null;
    if (norm(root) === norm(projReal)) why = 'the project itself';
    else if (isWithin(projReal, root)) why = 'contains the project';
    else if (engineHome && isWithin(engineHome, root)) why = "the engine's own home";
    else if (/^[a-z]:$/i.test(norm(root)) || norm(root) === '/') why = 'a drive root';
    else if (containers.includes(norm(root))) why = "a container of the user's files";
    else if (projCommon && commonDirOf(root) && norm(commonDirOf(root)) === norm(projCommon)) why = "the project's own repository (another worktree)";
    if (why) excluded.push({ repo: root, why });
    else checked.push(root);
  }
  // review r1: a missing input INSIDE the project is missing too - no exemption
  const missingInputs = inputPaths(inputsSection(planText), projReal).filter((p) => !exists(p));
  return { checked, excluded, unresolved, missingInputs };
}

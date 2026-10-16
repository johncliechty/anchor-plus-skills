// engine/porcelain.mjs — Wave 2: git's own answer to "what does git hold?".
//
// Every Wave-2 decision that matters — is this a SAVE candidate, may this path
// even reach the removal debate, which secret remediation applies — is a
// question about a path's TRACKING CLASS. There is exactly one trustworthy
// source for that answer and it is `git status --porcelain=v2`, so this module
// parses it and nothing else infers tracking state from the filesystem.
//
// The VERBATIM porcelain line is carried on every record. A SAVE finding shows
// the user git's own words, not our summary of them, and the removal exclusion
// log records the evidence that produced the exclusion — both requirements are
// impossible to honour if the raw line is discarded at parse time.
//
// One subtlety worth stating: `git status` reports CHANGED and UNTRACKED paths.
// A tracked-and-clean file — the only class eligible for a git REMOVE — appears
// NOWHERE in its output. Classifying by absence alone would therefore call an
// ignored file "tracked and clean" and make it removable through the git path,
// which is precisely backwards (git does not hold it at all). So the index is
// read separately via `git ls-files`, and absence from BOTH is reported as
// 'ignored' — a path git does not hold — never as tracked-clean.

import { toPosixRel } from './glob.mjs';

/** A path's relationship to git. The whole of Wave 2 branches on this. */
export const TRACKING = Object.freeze({
  TRACKED_CLEAN: 'tracked-clean',
  TRACKED_MODIFIED: 'tracked-modified',
  STAGED: 'staged',
  UNMERGED: 'unmerged',
  UNTRACKED: 'untracked',
  IGNORED: 'ignored',
  /** No repository at all (ctx.git === null). */
  NON_GIT: 'non-git',
});

/** Classes git DOES hold the content of — the only ones a git commit can undo. */
export const GIT_HELD = Object.freeze(new Set([
  TRACKING.TRACKED_CLEAN, TRACKING.TRACKED_MODIFIED, TRACKING.STAGED, TRACKING.UNMERGED,
]));

/**
 * Undo a git C-style quoted path ("a\tb" / "\303\251.txt"). git only quotes
 * when core.quotePath applies, so the common path through here is the
 * identity — but a tab in a filename must not shift every subsequent field.
 */
export function unquotePath(raw) {
  const s = String(raw);
  if (!s.startsWith('"')) return s;
  const body = s.slice(1, -1);
  const bytes = [];
  for (let i = 0; i < body.length; i++) {
    if (body[i] !== '\\') { bytes.push(body.charCodeAt(i)); continue; }
    const n = body[++i];
    if (n === undefined) break;
    if (n >= '0' && n <= '7') {
      bytes.push(parseInt(body.slice(i, i + 3), 8));
      i += 2;
      continue;
    }
    const simple = { n: 10, t: 9, r: 13, b: 8, f: 12, v: 11, a: 7, '\\': 92, '"': 34 };
    bytes.push(simple[n] !== undefined ? simple[n] : n.charCodeAt(0));
  }
  return Buffer.from(bytes).toString('utf8');
}

function classFromXY(x, y) {
  if (x === 'U' || y === 'U') return TRACKING.UNMERGED;
  if (x !== '.') return TRACKING.STAGED;
  if (y !== '.') return TRACKING.TRACKED_MODIFIED;
  return TRACKING.TRACKED_CLEAN;
}

/**
 * Parse `git status --porcelain=v2 --branch --untracked-files=all` output.
 *
 * @param {string} text
 * @returns {{branch: object, records: object[], byPath: Map<string, object>}}
 */
export function parsePorcelainV2(text) {
  const branch = { oid: null, head: null, upstream: null, ahead: null, behind: null };
  const records = [];

  for (const line of String(text).split('\n')) {
    if (!line) continue;
    const type = line[0];

    if (type === '#') {
      const m = /^# branch\.(\S+)\s+(.*)$/.exec(line);
      if (!m) continue;
      if (m[1] === 'oid') branch.oid = m[2] === '(initial)' ? null : m[2];
      else if (m[1] === 'head') branch.head = m[2] === '(detached)' ? null : m[2];
      else if (m[1] === 'upstream') branch.upstream = m[2];
      else if (m[1] === 'ab') {
        const ab = /^\+(\d+)\s+-(\d+)$/.exec(m[2]);
        if (ab) { branch.ahead = Number(ab[1]); branch.behind = Number(ab[2]); }
      }
      continue;
    }

    if (type === '?' || type === '!') {
      const p = toPosixRel(unquotePath(line.slice(2)));
      records.push({
        kind: type === '?' ? 'untracked' : 'ignored',
        path: p,
        xy: type === '?' ? '??' : '!!',
        staged: false,
        unstaged: type === '?',
        trackingClass: type === '?' ? TRACKING.UNTRACKED : TRACKING.IGNORED,
        raw: line,
      });
      continue;
    }

    if (type === '1' || type === '2' || type === 'u') {
      const fields = line.split(' ');
      const xy = fields[1] || '..';
      // Field counts are fixed by the porcelain=v2 format; the path is
      // everything after them (and may itself contain spaces).
      const pathStartField = type === '1' ? 8 : (type === '2' ? 9 : 10);
      let rest = fields.slice(pathStartField).join(' ');
      let origPath = null;
      if (type === '2') {
        // "<path>\t<origPath>" for a rename/copy.
        const tab = rest.indexOf('\t');
        if (tab !== -1) {
          origPath = toPosixRel(unquotePath(rest.slice(tab + 1)));
          rest = rest.slice(0, tab);
        }
      }
      const p = toPosixRel(unquotePath(rest));
      records.push({
        kind: type === '1' ? 'ordinary' : (type === '2' ? 'renamed' : 'unmerged'),
        path: p,
        ...(origPath ? { origPath } : {}),
        xy,
        staged: xy[0] !== '.',
        unstaged: xy[1] !== '.',
        trackingClass: type === 'u' ? TRACKING.UNMERGED : classFromXY(xy[0], xy[1]),
        raw: line,
      });
      continue;
    }
    // Any other leading byte is a format the parser does not claim to know; it
    // is dropped rather than guessed at, and the caller's coverage note says so.
  }

  const byPath = new Map();
  for (const r of records) byPath.set(r.path, r);
  return { branch, records, byPath };
}

/**
 * Read and index the repository's status + index for a run. Memoised on
 * ctx.state so a run shells out to git exactly once no matter how many stages
 * ask — and so every stage necessarily agrees about every path's class.
 *
 * @param {object} ctx
 * @returns {Promise<null|object>} null when ctx.git is null (the git:null contract)
 */
export async function loadPorcelain(ctx) {
  if (ctx.state && ctx.state.porcelain !== undefined) return ctx.state.porcelain;
  if (!ctx.git) {
    if (ctx.state) ctx.state.porcelain = null;
    return null;
  }

  const text = await ctx.git.porcelain();
  const parsed = parsePorcelainV2(text);

  let tracked = new Set();
  let indexError = null;
  try {
    const { stdout } = await ctx.git.run(['ls-files', '-z']);
    tracked = new Set(String(stdout).split('\0').filter(Boolean).map(toPosixRel));
  } catch (err) {
    // An unreadable index is NOT "everything is clean" — it is a coverage gap,
    // reported as such by the caller. classify() degrades to 'unknown' so no
    // path can be silently promoted into the removable tracked-clean class.
    indexError = err && err.message ? err.message : String(err);
  }

  const view = {
    raw: text,
    branch: parsed.branch,
    records: parsed.records,
    byPath: parsed.byPath,
    tracked,
    indexError,

    /** The authoritative tracking class for one repo-relative path. */
    classify(rel) {
      const p = toPosixRel(rel);
      const rec = parsed.byPath.get(p);
      if (rec) return rec.trackingClass;
      if (indexError) return 'unknown';
      return tracked.has(p) ? TRACKING.TRACKED_CLEAN : TRACKING.IGNORED;
    },

    /** The verbatim porcelain line for a path, or null when git said nothing. */
    record(rel) {
      return parsed.byPath.get(toPosixRel(rel)) || null;
    },

    /** Paths git reported as untracked. */
    untracked() {
      return parsed.records.filter((r) => r.trackingClass === TRACKING.UNTRACKED).map((r) => r.path);
    },

    /** Paths git reported as tracked-with-changes (staged, unstaged or both). */
    changedTracked() {
      return parsed.records
        .filter((r) => r.trackingClass === TRACKING.TRACKED_MODIFIED
          || r.trackingClass === TRACKING.STAGED
          || r.trackingClass === TRACKING.UNMERGED)
        .map((r) => r.path);
    },

    /** Dirty-tree policy input: the count, recorded, never used to refuse. */
    dirtyCount() {
      return parsed.records.filter((r) => r.trackingClass !== TRACKING.IGNORED).length;
    },
  };

  if (ctx.state) ctx.state.porcelain = view;
  return view;
}

export default { TRACKING, GIT_HELD, parsePorcelainV2, loadPorcelain, unquotePath };

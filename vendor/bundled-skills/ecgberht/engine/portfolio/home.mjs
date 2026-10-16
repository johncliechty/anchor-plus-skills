/**
 * W4 - the ONE index home, resolved and never searched for.
 *
 * WHY THIS FILE EXISTS. "There is exactly one portfolio index" is a claim about LOOKUP
 * before it is a claim about storage. The moment two call sites each work out for
 * themselves where the index lives, there are two indexes: one verb writes under the
 * environment override, another under the default, and the portfolio silently splits in
 * half while every test stays green. So the resolution rule lives here, once, and every
 * verb from W5 onward reads its paths from this module rather than composing them.
 *
 * TWO RULES, BOTH LOAD-BEARING.
 *
 *  1. NEVER SEARCH. There is no walk, no "look upward for a .steward directory", no
 *     "try these three candidates and take the first that exists". Searching is how a
 *     store becomes ambient: it makes the answer depend on the current working directory
 *     and on which directories happen to exist, so the same command means different
 *     things in different shells, and a half-restored copy on the search path silently
 *     wins. This module therefore imports node:path and node:os and NOTHING ELSE - it
 *     cannot touch the filesystem even by accident, and test/w49-home-resolution.test.mjs
 *     asserts that absence of node:fs directly, because a rule enforced by discipline is
 *     a rule that lasts until the next hurried commit.
 *
 *  2. NEVER CONSULT A PER-PROJECT LOCATION. The in-root marker (marker.mjs) says which
 *     PROJECT a directory is; it never says where the INDEX is. If a marker could name an
 *     index home, then copying a project root would relocate the portfolio - which is the
 *     NG-3 clone hazard with the blast radius of the whole store rather than one row.
 *
 * RESOLUTION ORDER, closed:
 *   STEWARD_HOME, when set to a non-empty absolute path -> exactly that path.
 *   otherwise -> <user profile>/.steward/portfolio/
 *
 * A STEWARD_HOME that is set but empty, or set but relative, is a REFUSAL rather than a
 * silent fall-through to the default. The operator who typed `set STEWARD_HOME=` and the
 * operator who never set it at all mean different things, and quietly treating the first
 * as the second writes the portfolio somewhere they did not ask for.
 *
 * This module creates nothing. Directory creation belongs to the W5 write primitive,
 * which is the only code that may bring the home into existence.
 *
 * Stdlib only.
 */

import os from 'node:os';
import path from 'node:path';

/** The frozen contract's version. Changing the resolution order means home-v2. */
export const HOME_VERSION = 'index-home-v1';

/** The one environment variable that relocates the index. */
export const HOME_ENV = 'STEWARD_HOME';

/** The default home, relative to the user profile. Joined, never string-concatenated. */
export const DEFAULT_HOME_SEGMENTS = Object.freeze(['.steward', 'portfolio']);

/** Where a resolution came from. Reported on every result so a surprise is traceable. */
export const HOME_SOURCE = Object.freeze({
  ENV: 'STEWARD_HOME_ENV',
  USER_PROFILE: 'USER_PROFILE_DEFAULT',
});

/**
 * The file names inside the home, frozen here so no verb composes its own.
 *
 * The log and the snapshot are split by path on purpose (D-1): the log is only ever
 * appended to, the snapshot is only ever temp-written and renamed, and W5's
 * write-primitive lint asserts neither primitive can reach the other's path. Naming both
 * in one place is what lets that lint be a lookup rather than a guess.
 */
export const INDEX_FILES = Object.freeze({
  LOG: 'portfolio.jsonl',
  SNAPSHOT: 'portfolio-index.json',
  LOCK: 'portfolio.lock',
});

/** The refusals this module raises. Named, so a caller can branch on them. */
export const HOME_REFUSAL = Object.freeze({
  ENV_EMPTY: 'INDEX_HOME_ENV_EMPTY',
  ENV_NOT_ABSOLUTE: 'INDEX_HOME_ENV_NOT_ABSOLUTE',
  NO_USER_PROFILE: 'INDEX_HOME_NO_USER_PROFILE',
});

/** User-visible text per refusal. The operator reads these, so they say what to do. */
export const HOME_REFUSAL_TEXT = Object.freeze({
  [HOME_REFUSAL.ENV_EMPTY]:
    `${HOME_ENV} is set but empty. An empty override is not the same as no override, so ` +
    'the index home was not guessed: either unset it to use the default under your user ' +
    'profile, or set it to the absolute path you want the portfolio index to live at.',
  [HOME_REFUSAL.ENV_NOT_ABSOLUTE]:
    `${HOME_ENV} must be an absolute path. A relative override would resolve differently ` +
    'from every working directory, which is how one portfolio becomes several.',
  [HOME_REFUSAL.NO_USER_PROFILE]:
    'no user profile directory could be determined, so the default index home cannot be ' +
    `composed. Set ${HOME_ENV} to an absolute path to say where the index lives.`,
});

/**
 * An error carrying its refusal code, so callers branch on the code rather than on text.
 */
export class IndexHomeRefusal extends Error {
  /** @param {string} code @param {string} [detail] */
  constructor(code, detail = '') {
    const text = HOME_REFUSAL_TEXT[code] ?? code;
    super(detail ? `${code}: ${text} (${detail})` : `${code}: ${text}`);
    this.name = 'IndexHomeRefusal';
    this.code = code;
    this.text = text;
  }
}

/**
 * Resolve the ONE index home.
 *
 * Pure: it reads the environment object it is handed, joins strings, and returns. It does
 * not stat, does not create, and does not care whether the directory exists - "the index
 * home is missing" is an index-read state (W5), not a resolution failure. Keeping those
 * two apart is what stops a first run from being reported as a misconfiguration.
 *
 * @param {Record<string, string|undefined>} [env] defaults to process.env
 * @param {{homedir?: () => string}} [opts] injection point for the tests
 * @returns {{home: string, source: string, env_name: string, env_value: string|null,
 *            explicit: boolean, version: string}}
 */
export function resolveIndexHome(env = process.env, opts = {}) {
  const present = env !== null && env !== undefined && Object.prototype.hasOwnProperty.call(env, HOME_ENV);
  const raw = present ? env[HOME_ENV] : undefined;

  if (raw !== undefined && raw !== null) {
    const value = String(raw);
    if (value.trim() === '') throw new IndexHomeRefusal(HOME_REFUSAL.ENV_EMPTY);
    if (!path.isAbsolute(value)) {
      throw new IndexHomeRefusal(HOME_REFUSAL.ENV_NOT_ABSOLUTE, value);
    }
    return Object.freeze({
      home: path.resolve(value),
      source: HOME_SOURCE.ENV,
      env_name: HOME_ENV,
      env_value: value,
      explicit: true,
      version: HOME_VERSION,
    });
  }

  const homedir = typeof opts.homedir === 'function' ? opts.homedir : os.homedir;
  let profile;
  try {
    profile = homedir();
  } catch (err) {
    throw new IndexHomeRefusal(HOME_REFUSAL.NO_USER_PROFILE, err && err.code ? String(err.code) : '');
  }
  if (typeof profile !== 'string' || profile.trim() === '' || !path.isAbsolute(profile)) {
    throw new IndexHomeRefusal(HOME_REFUSAL.NO_USER_PROFILE, String(profile ?? ''));
  }

  return Object.freeze({
    home: path.join(profile, ...DEFAULT_HOME_SEGMENTS),
    source: HOME_SOURCE.USER_PROFILE,
    env_name: HOME_ENV,
    env_value: null,
    explicit: false,
    version: HOME_VERSION,
  });
}

/**
 * The three paths inside a home. Every index path in the system is one of these or a
 * sidecar derived from them (`<log>.torn-<seq>`, `<snapshot>.tmp-<pid>-<seq>`), and both
 * sidecar forms are composed HERE so the W5 lint has one place to look.
 *
 * @param {string} home an absolute home directory
 * @returns {{home: string, log: string, snapshot: string, lock: string}}
 */
export function indexPathsFor(home) {
  const abs = path.resolve(String(home));
  return Object.freeze({
    home: abs,
    log: path.join(abs, INDEX_FILES.LOG),
    snapshot: path.join(abs, INDEX_FILES.SNAPSHOT),
    lock: path.join(abs, INDEX_FILES.LOCK),
  });
}

/**
 * @param {Record<string, string|undefined>} [env]
 * @param {{homedir?: () => string}} [opts]
 * @returns {{home: string, log: string, snapshot: string, lock: string, source: string}}
 */
export function resolveIndexPaths(env = process.env, opts = {}) {
  const resolved = resolveIndexHome(env, opts);
  return Object.freeze({ ...indexPathsFor(resolved.home), source: resolved.source });
}

/**
 * The quarantine sidecar for a torn log tail (D-1 / W5). Named here so the log directory
 * can never be somewhere else than the log.
 *
 * @param {string} logPath @param {number} seq @returns {string}
 */
export function tornLogPathFor(logPath, seq) {
  return `${String(logPath)}.torn-${Number(seq)}`;
}

/**
 * The same-directory temp name the snapshot is written under before its rename (D-1).
 * Same directory is not a detail: rename is only atomic within a volume.
 *
 * @param {string} snapshotPath @param {number} pid @param {number} seq @returns {string}
 */
export function snapshotTempPathFor(snapshotPath, pid, seq) {
  return `${String(snapshotPath)}.tmp-${Number(pid)}-${Number(seq)}`;
}

/**
 * W18 - the RETIRED SEGMENT: the pre-compaction log, kept beside the compacted head.
 *
 * It is a sidecar rather than a deletion because compaction is the one operation that could
 * destroy the audit trail C7 depends on, and the plan's answer is that it does not: the old
 * bytes stay on disk under their own name until all three retirement preconditions hold and
 * an operator (or `steward compact --delete-retired`) says so. The seq in the name is the
 * compaction boundary, so two compactions cannot land on one file and an operator can line a
 * segment up against the head that replaced it.
 *
 * @param {string} logPath @param {number} seq the compaction boundary @returns {string}
 */
export function retiredSegmentPathFor(logPath, seq) {
  return `${String(logPath)}.retired-${Number(seq)}`;
}

/**
 * W18 - where the compacted head is assembled before it becomes the live log.
 *
 * SAME DIRECTORY, for the same reason the snapshot temp is: the final step is a rename, and
 * a rename is only atomic within a volume. The staging file is scratch - it is written line
 * by line through the D-1 append primitive and it is either renamed into place or removed;
 * nothing ever reads it as index content.
 *
 * @param {string} logPath @param {number} seq the compaction boundary @returns {string}
 */
export function compactStagingPathFor(logPath, seq) {
  return `${String(logPath)}.compacting-${Number(seq)}`;
}

/**
 * The compaction boundary a sidecar name carries, or null when the name is not one of ours.
 *
 * Parsing rather than globbing: `steward doctor` and the retirement verb both need to answer
 * "which segments are on disk", and a caller that matched on a substring would pick up a
 * `.retired-4.bak` an operator left behind and report it as a segment this engine wrote.
 *
 * @param {string} logPath @param {string} candidate @returns {number|null}
 */
export function retiredSegmentSeqOf(logPath, candidate) {
  const prefix = `${String(logPath)}.retired-`;
  const name = String(candidate);
  if (!name.startsWith(prefix)) return null;
  const tail = name.slice(prefix.length);
  if (!/^\d+$/.test(tail)) return null;
  return Number(tail);
}

/**
 * Is `candidate` inside `home`? Used by W5/W10 containment checks so "inside the index
 * home" is decided once, case-insensitively on Windows and with a separator boundary so
 * `<home>-backup` is never mistaken for a child of `<home>`.
 *
 * @param {string} home @param {string} candidate @returns {boolean}
 */
export function isInsideHome(home, candidate) {
  const rel = path.relative(path.resolve(String(home)), path.resolve(String(candidate)));
  if (rel === '') return true;
  if (path.isAbsolute(rel)) return false;
  return !rel.split(/[\\/]/).includes('..');
}

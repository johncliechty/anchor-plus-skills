/**
 * W10 - `steward rebuild`: the frozen rebuild equation, totality, and path containment.
 *
 * THE EQUATION, AND WHY ITS INPUT SET IS THE WHOLE POINT. C1 says the index is deletable and
 * rebuildable, and a rebuild is only a proof of that if it consumes EXACTLY the declared
 * input set I:
 *
 *     I = { the ONE log's events, replayed in `seq` order }
 *       ∪ { per-project files under each LIVE registered root, via inventory-v1 discovery }
 *
 * and nothing else. The previous snapshot is NOT in I - it is the artifact being replaced, so
 * reading it would make the rebuild a function of its own previous output and the byte-equal
 * claim would be circular rather than true. That exclusion is not left to good manners here:
 * every read this module performs goes through `inputOnlyFs`, a facade that REFUSES a read of
 * the snapshot path by name and journals every read it makes inside the index home. So "the
 * rebuilder never opened the deleted file" is a property of the code, and the test that
 * asserts it reads a journal rather than trusting a promise.
 *
 * TOTALITY, STATED AS AN EQUATION BECAUSE PROSE CANNOT BE COUNTED. Every discovered file
 * yields exactly ONE of {a parsed row, an UNPARSEABLE row carrying reason + path, an
 * UNCLASSIFIED row carrying its path}, so
 *
 *     parsed + unparseable + unclassified == discovered
 *
 * holds over the inventory-v1 paths. A file that is silently skipped is the failure mode this
 * equation exists to make impossible to ship: it would leave the portfolio smaller than the
 * disk with nothing anywhere saying so. A file that cannot even be READ is UNPARSEABLE with
 * reason UNREADABLE - not dropped, because "we could not read it" is a finding, not an absence.
 *
 * PATH CONTAINMENT (NG-2). Every ingested path must resolve INSIDE its project's registered
 * root after `path.resolve`. A recorded path that escapes - `../../elsewhere/receipt.json`, or
 * an absolute path pointing at another project - is refused with integrity code TAMPERED,
 * rendered loudly, and its content is NEVER ingested. The check is on the RESOLVED path
 * because a string test for '..' is defeated by the first symlink or the first `%2e%2e`, and
 * because containment is a question about where the bytes actually are.
 *
 * ONE DERIVATION, NO FORK (the minimum frozen contract). `deriveRow` from
 * engine/portfolio/derive.mjs is the sole producer of DERIVED rows on BOTH paths: the W9
 * write path calls it at the moment a file is written, and this module calls it again from the
 * bytes it discovers later. This file therefore never composes a row of its own - it derives,
 * then attaches the two fields the log owns (`seq`, and the lineage `supersedes` the log
 * records). And it CHECKS: a rebuilt row whose fingerprint differs from the log's row for the
 * same bytes is recorded in `forks`, which is the one thing in this artifact that must always
 * be empty.
 *
 * D-2, AND EXACTLY HOW FAR IT WEAKENS BYTE-EQUALITY. Byte-equality is asserted over `body`.
 * `freshness` is the ONE named block permitted to carry clock- and host-varying values, and
 * its field set is closed by W4. That is the only weakening, and it is why presence and
 * freshness live in that block rather than in `body`: they are answers about the filesystem at
 * this instant, and a body carrying them would differ between two rebuilds of one portfolio
 * for a reason that has nothing to do with what the portfolio contains.
 *
 * WHAT THIS MODULE NEVER DOES. It never appends to the log (a rebuild that appended would
 * allocate new seqs and could not be byte-equal to itself), never mints an identity (nothing
 * here imports the minter), and never removes a row: a row whose file is gone is RETAINED and
 * named, because the North Star forbids the silent shrink - and a root that is gone says so
 * out loud, as one explicit unknown row reconstructed from NATIVE events alone by
 * engine/portfolio/root-status.mjs.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  INDEX_READ_CODE,
  ORDERING_FIELD,
  WALL_CLOCK_FIELD,
  indexOutcome,
  indexPathsFrom,
  inspectIndexHome,
  isIndexRefusal,
  logEventLine,
  readLogHead,
  recoveryOutcome,
  refusingHazards,
  replayEvents,
  withPortfolioLock,
} from '../append-log.mjs';
import {
  SNAPSHOT_SCHEMA,
  serializeSnapshot,
  splitCanonicalText,
  writeCanonicalSnapshot,
} from './canonical.mjs';
import { CAPS } from './caps.mjs';
import { hashBytes } from './commit-intent.mjs';
import {
  DERIVABLE_CLASSES,
  deriveRow,
  derivedRowsInLog,
  isDerivedEvent,
  rowFingerprint,
  rowIdentity,
  sourceRecordFor,
} from './derive.mjs';
import { contentHashesFor } from './content-hash.mjs';
import { SURFACE, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import { isInsideHome } from './home.mjs';
import { BINDING, classifyMarkerReads, countProjects, pathKey } from './identity.mjs';
import {
  CLASS,
  EXTENDED_PREFIX,
  HAZARD,
  INVENTORY_VERSION,
  PARSE_REASON,
  openablePath,
  parseBytes,
  toPosix,
  walkRoot,
} from './inventory.mjs';
import { readMarker } from './marker.mjs';
import { materializeRegistry } from './registry.mjs';
import {
  classifyRootStatus,
  replayedRowFreshness,
  rootStatusOf,
  sortUnknownRows,
  unknownRowFromNative,
} from './root-status.mjs';
import {
  FRESHNESS_KEYS,
  PER_PROJECT_KEYS,
  emptyFreshnessBlock,
  perProjectFreshness,
} from './snapshot-shape.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The rebuild's frozen version. Changing what the equation consumes means rebuild-v2. */
export const REBUILD_VERSION = 'rebuild-v1';

/** The receipt this verb hands its caller. */
export const REBUILD_RECEIPT_SCHEMA = 'rebuild-receipt-v1';

/** The verb's name, as an operator types it. */
export const REBUILD_VERB = 'rebuild';

/** The failure-table surface these rows belong to. */
export const REBUILD_SURFACE = SURFACE.REBUILD;

/**
 * Input set I, named as data so a later reader can enumerate it instead of inferring it from
 * the call graph - and so adding a source is a visible edit here rather than an extra
 * `readFileSync` somewhere in the middle.
 */
export const REBUILD_INPUT = Object.freeze({
  LOG_EVENTS: 'the ONE log, replayed in seq order: NATIVE membership always, DERIVED rows for non-live roots',
  LIVE_ROOT_FILES: 'per-project files under each LIVE registered root, discovered through inventory-v1',
});

/**
 * What is deliberately NOT in I. The previous snapshot is the artifact being replaced; a
 * rebuild that read it would be a function of its own previous output.
 */
export const REBUILD_EXCLUDED_INPUT = Object.freeze([
  'the previous snapshot (it is DERIVED, deletable, and the thing being rebuilt)',
]);

/** The region byte-equality is asserted over, per D-2. Stated so a test can cite it. */
export const BYTE_EQUAL_REGION = 'body';

// -- the row codes -------------------------------------------------------------

/**
 * The class-varying rows are named `<STEM>_<SUFFIX>`. Same table as the write path's, for the
 * same reason: a fourth class would be one edit rather than a search.
 */
const CLASS_SUFFIX = Object.freeze({
  [CLASS.RECEIPT]: 'RECEIPT',
  [CLASS.INSTRUMENT]: 'INSTRUMENT',
  [CLASS.ROADMAP_EVENT]: 'ROADMAP_EVENT',
});

/** The class-varying rebuild row stems. */
export const REBUILD_CLASS_STEM = Object.freeze({
  UNPARSEABLE: 'REBUILD_UNPARSEABLE',
  MOJIBAKE: 'REBUILD_MOJIBAKE',
  EMPTY: 'REBUILD_EMPTY',
  RETAINED_UNKNOWN: 'REBUILD_RETAINED_UNKNOWN',
});

/** The rebuild rows that do not vary by class. */
export const REBUILD_CODE = Object.freeze({
  ROOT_ABSENT: 'REBUILD_ROOT_ABSENT',
  ROOT_UNREACHABLE: 'REBUILD_ROOT_UNREACHABLE',
  LOG_ABSENT: 'REBUILD_LOG_ABSENT',
  WALK_BOUND_EXCEEDED: 'REBUILD_WALK_BOUND_EXCEEDED',
  LOG_TORN: 'REBUILD_LOG_TORN',
  PATH_ESCAPE: 'REBUILD_PATH_ESCAPE',
  IDENTITY_CONFLICT: 'REBUILD_IDENTITY_CONFLICT',
  UNCLASSIFIED: 'REBUILD_UNCLASSIFIED',
  INDEX_UNWRITABLE: 'REBUILD_INDEX_UNWRITABLE',
  NO_PROJECTS: 'REBUILD_NO_PROJECTS',
  SKIPPED_REPARSE: 'REBUILD_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'REBUILD_PATH_TOO_LONG',
  CASE_COLLISION: 'REBUILD_CASE_COLLISION',
});

/**
 * The success code. It is NOT a failure-table row - the tables describe failure states, and a
 * clean rebuild is not one - so it carries its own status and sentence here, exactly the way
 * W7's REGISTER_OK does.
 */
export const REBUILD_OK = 'REBUILD_OK';

/** @type {Readonly<Record<string, {status: string, text: string}>>} */
export const REBUILD_ROWS = Object.freeze({
  [REBUILD_OK]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'rebuild OK'),
    text:
      'Rebuilt the portfolio index from {projects} registered project(s): {discovered} '
      + 'discovered file(s) across {live} live root(s) yielded {parsed} parsed, {unparseable} '
      + 'unparseable and {unclassified} unclassified, plus {replayed} row(s) replayed from the '
      + 'log for non-live roots. The snapshot was written from the log and the live roots '
      + 'alone; the previous snapshot was never read.',
  }),
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * The class-varying row code for a stem.
 *
 * @param {string} stem one of REBUILD_CLASS_STEM @param {string} className
 * @returns {string}
 */
export function rebuildClassCode(stem, className) {
  const suffix = CLASS_SUFFIX[className];
  if (suffix === undefined) {
    throw new Error(`rebuild: ${JSON.stringify(className)} is not a tracked content class`);
  }
  return `${stem}_${suffix}`;
}

/**
 * An outcome for a rebuild row. Frozen failure rows are read from the table so the status and
 * the sentence have exactly one home; REBUILD_OK is the one code defined above.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function rebuildOutcome(code, params = {}, extra = {}) {
  const local = REBUILD_ROWS[code];
  if (local !== undefined) {
    return Object.freeze({
      ok: extra.ok !== false,
      code,
      surface: REBUILD_SURFACE,
      status: local.status,
      text: fill(local.text, params),
      detail: Object.freeze({ ...params }),
    });
  }
  return rowOutcome(code, params, extra);
}

/** @returns {ReadonlyArray<string>} every frozen rebuild row code, for a test that enumerates */
export function rebuildRowCodes() {
  return Object.freeze(rowsForSurface(REBUILD_SURFACE).map((r) => r.code));
}

/**
 * The rows this wave is responsible for turning green. The table records the wave that owns
 * each row, so the list is READ rather than restated: W11's absent-root rows and W17's
 * lost-log row are not W10's to claim, and a list typed by hand here would quietly claim them.
 *
 * @returns {ReadonlyArray<string>}
 */
export function rebuildRowsOwnedByThisWave() {
  return Object.freeze(
    rowsForSurface(REBUILD_SURFACE).filter((r) => r.wave === 'W10').map((r) => r.code),
  );
}

// -- refusals that belong to the caller ---------------------------------------

/**
 * Not failure-table rows and carrying no STATUS-v1 status, on purpose: an operator cannot act
 * on "the rebuilder tried to read the artifact it is replacing". That is a defect in code,
 * and putting it in the operator's table would be telling them to fix ours.
 */
export const REBUILD_REFUSAL = Object.freeze({
  SNAPSHOT_IS_NOT_INPUT: 'REBUILD_SNAPSHOT_IS_NOT_INPUT',
});

/** A refusal that names the rule it enforces. */
export class RebuildRefusal extends Error {
  /** @param {string} code @param {string} detail */
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = 'RebuildRefusal';
    this.code = code;
    this.detail = detail;
  }
}

// -- the input-only filesystem facade -----------------------------------------

/** The calls that can turn a path into bytes. Every one of them is guarded. */
export const GUARDED_READ_CALLS = Object.freeze([
  'readFileSync',
  'readFile',
  'openSync',
  'open',
  'createReadStream',
  'copyFileSync',
]);

/**
 * Resolve a path the way the guard compares them: the extended-length prefix removed first,
 * so a long path cannot slip past the comparison by wearing `\\?\`.
 *
 * @param {unknown} p @returns {string}
 */
export function comparablePath(p) {
  const raw = String(p ?? '');
  const bare = raw.startsWith(EXTENDED_PREFIX) ? raw.slice(EXTENDED_PREFIX.length) : raw;
  return pathKey(bare);
}

/**
 * An `fs` facade that cannot read the snapshot and says what it read inside the index home.
 *
 * This is the mechanism behind "rebuild never reads the old snapshot". Stating the rule in a
 * comment would leave it true until the first convenient `readFileSync`; stating it as a
 * facade means the convenient read throws, at the call site, with the rule in the message.
 *
 * The journal is bounded to reads INSIDE the index home, which is exactly the claim's scope -
 * a rebuild reads thousands of project files and none of them are the artifact.
 *
 * @param {object|undefined} base the fs to delegate to
 * @param {{home: string, snapshot: string}} paths
 * @param {{reads: Array<object>, refused: Array<object>, total: number}} journal
 * @returns {object}
 */
export function inputOnlyFs(base, paths, journal) {
  const snapshotKey = comparablePath(paths.snapshot);
  const facade = { ...(base ?? fs) };

  const note = (call, target) => {
    journal.total += 1;
    const key = comparablePath(target);
    if (key === snapshotKey) {
      const entry = Object.freeze({ call, path: String(target) });
      journal.refused.push(entry);
      throw new RebuildRefusal(
        REBUILD_REFUSAL.SNAPSHOT_IS_NOT_INPUT,
        `${call}() was asked to read ${paths.snapshot}, which is the artifact this rebuild `
        + 'replaces. The snapshot is DERIVED and is not in the rebuild equation\'s input set; a '
        + 'rebuild that read it would be a function of its own previous output.',
      );
    }
    if (isInsideHome(paths.home, String(target).replace(EXTENDED_PREFIX, ''))) {
      journal.reads.push(Object.freeze({ call, path: String(target) }));
    }
  };

  for (const call of GUARDED_READ_CALLS) {
    const original = facade[call];
    if (typeof original !== 'function') continue;
    facade[call] = (target, ...rest) => {
      note(call, target);
      return original(target, ...rest);
    };
  }
  return facade;
}

/** @returns {{reads: Array<object>, refused: Array<object>, total: number}} a fresh journal */
export function newReadJournal() {
  return { reads: [], refused: [], total: 0 };
}

// -- path containment ----------------------------------------------------------

/**
 * Is `candidate` inside `rootAbs` after resolution?
 *
 * Delegated to home.mjs's containment test rather than reimplemented: "inside a directory" is
 * decided ONCE in this codebase, case-insensitively and with a separator boundary, so
 * `<root>-backup` is never mistaken for a child of `<root>`. Two containment rules would be
 * one rule and one hole.
 *
 * @param {string} rootAbs @param {string} candidate @returns {boolean}
 */
export function isInsideRoot(rootAbs, candidate) {
  return isInsideHome(rootAbs, candidate);
}

/**
 * Resolve a recorded root-relative path against its root, and refuse the ones that escape.
 *
 * The resolution is what does the work. `receipts/../../../etc/passwd` is a perfectly ordinary
 * string until it is resolved, and an absolute path recorded in a row resolves to itself -
 * ignoring the root entirely - which is precisely the case a string test for '..' misses.
 *
 * @param {string} rootAbs @param {string} recordedPath as stored on the row (POSIX separators)
 * @returns {Readonly<{ok: boolean, abs: string, rel: string, outcome: Readonly<object>|null}>}
 */
export function containedPath(rootAbs, recordedPath) {
  const root = path.resolve(String(rootAbs));
  const recorded = String(recordedPath ?? '');
  const abs = path.resolve(root, recorded.split('/').join(path.sep));
  if (isInsideRoot(root, abs) && abs !== root) {
    return Object.freeze({ ok: true, abs, rel: toPosix(path.relative(root, abs)), outcome: null });
  }
  return Object.freeze({
    ok: false,
    abs,
    rel: recorded,
    outcome: rebuildOutcome(REBUILD_CODE.PATH_ESCAPE, {
      path: recorded,
      resolved: abs,
      root,
    }),
  });
}

// -- the log head --------------------------------------------------------------

/**
 * The hash of the log head at its sequence: the sha256 of the head event's LINE, exactly as
 * that line sits on disk.
 *
 * Recomputable from the log by anything that can read it, which is what makes W14's
 * stale-restore detection possible: a snapshot claiming a head_seq whose head hash does not
 * match the log's is a snapshot from a different history. An empty log has no head, and that
 * is reported as null rather than as the hash of nothing.
 *
 * @param {ReadonlyArray<object>} events @returns {string|null}
 */
export function logHeadSha256(events) {
  const ordered = replayEvents(Array.isArray(events) ? events : []);
  if (ordered.length === 0) return null;
  return hashBytes(Buffer.from(logEventLine(ordered[ordered.length - 1]), 'utf8'));
}

/**
 * Read input set I's first half: the log, and ONLY the log.
 *
 * This is deliberately not `openIndexForRead` - that function reads the snapshot too, which is
 * correct for every other surface and forbidden here. The lock is still taken, for the same
 * reason a read takes it anywhere: a reader that runs mid-append can observe a fragment, and
 * "the log looked torn for a moment" is indistinguishable downstream from "the log is torn".
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, boundMs?: number,
 *          staleMs?: number, quarantine?: boolean, lockOpts?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function readRebuildInput(opts = {}) {
  const paths = indexPathsFrom(opts);
  const journal = newReadJournal();
  const guarded = inputOnlyFs(opts.fsx, paths, journal);

  let homeStat;
  try {
    homeStat = guarded.statSync(openablePath(paths.home));
  } catch (err) {
    return Object.freeze({
      ok: false,
      paths,
      outcome: indexOutcome(
        err && err.code === 'ENOENT' ? INDEX_READ_CODE.HOME_ABSENT : INDEX_READ_CODE.HOME_UNREACHABLE,
        { home: paths.home, errno: (err && err.code) || '' },
      ),
      events: Object.freeze([]),
      head_seq: 0,
      journal,
      fsx: guarded,
    });
  }
  if (!homeStat.isDirectory()) {
    return Object.freeze({
      ok: false,
      paths,
      outcome: indexOutcome(INDEX_READ_CODE.HOME_UNREACHABLE, {
        home: paths.home,
        errno: 'ENOTDIR',
      }),
      events: Object.freeze([]),
      head_seq: 0,
      journal,
      fsx: guarded,
    });
  }

  // The log is not in the deletable set (that is W17's whole subject), so its absence is a
  // DIFFERENT fact from an empty portfolio: the home exists, so something was here.
  let logPresent = true;
  try {
    guarded.statSync(openablePath(paths.log));
  } catch (err) {
    if (err && err.code === 'ENOENT') logPresent = false;
  }
  if (!logPresent) {
    return Object.freeze({
      ok: false,
      paths,
      outcome: rebuildOutcome(REBUILD_CODE.LOG_ABSENT, { home: paths.home, path: paths.log }),
      events: Object.freeze([]),
      head_seq: 0,
      journal,
      fsx: guarded,
    });
  }

  const hazards = inspectIndexHome(paths, { fsx: guarded });

  try {
    return withPortfolioLock(
      paths,
      () => {
        const head = readLogHead(paths.log, {
          fsx: guarded,
          write: false,
          quarantine: opts.quarantine,
        });
        if (!head.ok) {
          return Object.freeze({
            ok: false,
            paths,
            outcome: Object.freeze({ ...head.outcome }),
            events: Object.freeze([]),
            head_seq: head.head_seq ?? 0,
            hazards: Object.freeze(hazards),
            journal,
            fsx: guarded,
          });
        }
        return Object.freeze({
          ok: true,
          paths,
          outcome: null,
          events: Object.freeze(head.events),
          head_seq: head.head_seq,
          head_sha256: logHeadSha256(head.events),
          recovery: head.recovery,
          // A torn tail is quarantined and COUNTED before replay, so the rebuild proceeds from
          // a known head rather than an ambiguous one. It is reported, never swallowed.
          torn: recoveryOutcome(head.recovery, REBUILD_CODE.LOG_TORN),
          hazards: Object.freeze(hazards),
          blocking_hazards: Object.freeze(refusingHazards(hazards)),
          // Stated in the receipt so the claim is data rather than prose.
          snapshot_read: false,
          journal,
          fsx: guarded,
        });
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_READ_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) {
      return Object.freeze({
        ok: false,
        paths,
        outcome: err.outcome,
        events: Object.freeze([]),
        head_seq: 0,
        journal,
        fsx: guarded,
      });
    }
    throw err;
  }
}

// -- discovery: input set I's second half -------------------------------------

/** How the walk's hazard codes map onto the rebuild table. */
const HAZARD_ROW = Object.freeze({
  [HAZARD.SKIPPED_REPARSE]: REBUILD_CODE.SKIPPED_REPARSE,
  [HAZARD.PATH_TOO_LONG]: REBUILD_CODE.PATH_TOO_LONG,
  [HAZARD.CASE_COLLISION]: REBUILD_CODE.CASE_COLLISION,
  [HAZARD.WALK_CAP_REACHED]: REBUILD_CODE.WALK_BOUND_EXCEEDED,
  [HAZARD.UNREACHABLE]: REBUILD_CODE.ROOT_UNREACHABLE,
});

/**
 * The rebuild row a walk hazard becomes, or null where the frozen axis has no row for it.
 *
 * SKIPPED_CYCLE is the null case and stays null on purpose: W2 named it because a re-entered
 * directory is not a reparse point, and folding it into the nearest row would be exactly the
 * laundering NG-2 forbids. It is still carried into the artifact under its own W2 code.
 *
 * @param {string} hazardCode @returns {string|null}
 */
export function hazardRowFor(hazardCode) {
  return HAZARD_ROW[hazardCode] ?? null;
}

/** The parse reasons that get their own named row rather than the generic one. */
const PARSE_REASON_STEM = Object.freeze({
  [PARSE_REASON.MOJIBAKE]: REBUILD_CLASS_STEM.MOJIBAKE,
});

/**
 * Every file under one root, classified, with its bytes read for the classes that carry rows.
 *
 * The walk is W2's - order-deterministic, reparse points recorded and not followed, cycles
 * refused, MAX_PATH opened through the extended prefix - because "delete-and-rebuild is
 * deterministic" is false the moment the walk order is not.
 *
 * @param {string} rootAbs
 * @param {{fsx?: object, fs?: object, maxEntries?: number}} [opts]
 * @returns {Readonly<object>}
 */
export function discoverRoot(rootAbs, opts = {}) {
  const fsx = opts.fsx ?? opts.fs ?? fs;
  const walk = walkRoot(rootAbs, { ...opts, fs: fsx });
  const files = [];

  for (const entry of walk.files) {
    const contained = containedPath(walk.root, toPosix(entry.rel));
    if (!contained.ok) {
      // A walk cannot produce an escaping path, so this branch is a defence rather than an
      // expectation - and a defence that is only asserted in prose is one nobody has run.
      files.push(Object.freeze({
        class: entry.class,
        rel: toPosix(entry.rel),
        abs: entry.abs,
        contained: false,
        outcome: contained.outcome,
        bytes: null,
        readable: false,
        errno: null,
        hazards: Object.freeze(entry.hazards ?? []),
      }));
      continue;
    }

    // Only the classes that produce a row (or an identity observation) are read. An
    // UNCLASSIFIED file is counted by its PATH; reading its bytes would be the first step
    // toward ingesting something inventory-v1 never ratified.
    const wanted = entry.class !== null;
    let bytes = null;
    let readable = wanted === false;
    let errno = null;
    if (wanted) {
      try {
        // encoding-lint: raw-bytes - the hash must be over the bytes as they are on disk, and
        // MOJIBAKE is a named state that a decoded read silently erases.
        bytes = fsx.readFileSync(openablePath(entry.abs));
        readable = true;
      } catch (err) {
        errno = (err && err.code) || String(err);
      }
    }

    files.push(Object.freeze({
      class: entry.class,
      rel: toPosix(entry.rel),
      abs: entry.abs,
      contained: true,
      outcome: null,
      bytes: bytes === null ? null : (Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes)),
      readable,
      errno,
      hazards: Object.freeze(entry.hazards ?? []),
    }));
  }

  files.sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
  return Object.freeze({
    root: walk.root,
    presence: walk.presence,
    reason: walk.reason,
    files: Object.freeze(files),
    hazards: Object.freeze(walk.hazards),
    excluded: Object.freeze(walk.excluded),
    truncated: walk.truncated === true,
    entries_seen: walk.entries_seen,
  });
}

// -- identity: one pass, one count per project --------------------------------

/**
 * Every location this log has ever named for a project.
 *
 * This is the closed, enumerable set the engine can inspect WITHOUT a portfolio-wide search:
 * the registered root, every endpoint of every recorded reconcile, and the current binding.
 * It matters because NG-3's clone is detected here - a root copied wholesale leaves the SAME
 * project_id live in two of these directories at once, and both get named rather than one
 * silently winning. A path nothing in the log ever mentioned is not searched for: C8 forbids
 * the walk, and W12's `--scan` is the explicit, operator-driven route for candidates.
 *
 * @param {{root: string, current_path: string, moves?: ReadonlyArray<object>}} project
 * @param {ReadonlyArray<string>} [extra] caller-supplied candidate directories (W12 feeds these)
 * @returns {ReadonlyArray<string>} absolute, de-duplicated by the NG-3 path key, sorted
 */
export function knownLocationsFor(project, extra = []) {
  const seen = new Map();
  const add = (p) => {
    if (typeof p !== 'string' || p.trim() === '') return;
    const abs = path.resolve(p);
    const key = pathKey(abs);
    if (!seen.has(key)) seen.set(key, abs);
  };
  add(project.root);
  for (const move of project.moves ?? []) {
    add(move.from_path);
    add(move.to_path);
  }
  add(project.current_path);
  for (const p of extra ?? []) add(p);
  return Object.freeze([...seen.values()].sort((a, b) => (pathKey(a) < pathKey(b) ? -1 : 1)));
}

/**
 * Classify identity across the WHOLE pass, from the markers at every known location.
 *
 * One pass, because "the same id at two paths" is only a conflict when both were seen in the
 * same sweep - the same id at two paths across two runs is an ordinary move, and conflating
 * them would report a conflict every time a project is relocated.
 *
 * @param {ReadonlyArray<object>} projects the registry view's projects
 * @param {{fsx?: object, candidates?: Record<string, ReadonlyArray<string>>}} [opts]
 * @returns {Readonly<{classification: object, reads: ReadonlyArray<object>,
 *          byId: Map<string, object>}>}
 */
export function classifyIdentityPass(projects, opts = {}) {
  const fsx = opts.fsx ?? fs;
  const reads = [];
  for (const project of projects ?? []) {
    const extra = (opts.candidates ?? {})[project.project_id] ?? [];
    for (const location of knownLocationsFor(project, extra)) {
      const read = readMarkerAt(location, fsx);
      reads.push(Object.freeze({ ...read, project_id_expected: project.project_id }));
    }
  }
  const classification = classifyMarkerReads(reads);
  const byId = new Map();
  for (const entry of classification.projects) byId.set(entry.project_id, entry);
  return Object.freeze({ classification, reads: Object.freeze(reads), byId });
}

/**
 * Read the marker at one directory. Wrapped so the import stays in one place and so a
 * directory that does not exist is a result rather than a throw.
 *
 * @param {string} rootAbs @param {object} fsx @returns {object}
 */
function readMarkerAt(rootAbs, fsx) {
  return readMarker(rootAbs, { fs: fsx });
}

// -- the totality equation ----------------------------------------------------

/**
 * The equation, as a function so it can be asserted rather than described.
 *
 * TWO equations, not one, and both exact:
 *
 *     parsed + unparseable + unclassified == discovered      the frozen totality equation
 *     discovered + refused                == walk_files      nothing the walk saw is invisible
 *
 * The second exists because a path refused for escaping its root is stopped BEFORE
 * classification - it never becomes an input, so it is not one of `discovered`'s three
 * outcomes - and a count that simply dropped it would be the silent skip the first equation is
 * there to prevent, moved one step earlier.
 *
 * @param {{discovered?: number, parsed?: number, unparseable?: number, unclassified?: number,
 *          refused?: number, walk_files?: number}} counts
 * @returns {Readonly<object>}
 */
export function totalityOf(counts) {
  const discovered = Number(counts.discovered ?? 0);
  const parsed = Number(counts.parsed ?? 0);
  const unparseable = Number(counts.unparseable ?? 0);
  const unclassified = Number(counts.unclassified ?? 0);
  // The walk-side refusals only. A refusal on the log-replay path did not come from the walk,
  // so counting it here would break an equation about the walk for a reason unrelated to it.
  const refused = Number(counts.refused_discovery ?? counts.refused ?? 0);
  const walkFiles = Number(counts.walk_files ?? discovered + refused);
  const accounted = parsed + unparseable + unclassified;
  return Object.freeze({
    balanced: accounted === discovered,
    walk_accounted: discovered + refused === walkFiles,
    discovered,
    accounted,
    parsed,
    unparseable,
    unclassified,
    refused,
    walk_files: walkFiles,
    text:
      `parsed ${parsed} + unparseable ${unparseable} + unclassified ${unclassified} = `
      + `${accounted}, discovered ${discovered}; discovered ${discovered} + refused ${refused} `
      + `= ${discovered + refused}, walked ${walkFiles}`,
  });
}

// -- rows ----------------------------------------------------------------------

/**
 * A row as it goes into `body`: the log's ordering field kept, its wall clock dropped.
 *
 * Exported for the D-3 re-materializer (W13), which folds the log tail into the body and must
 * shape a row EXACTLY as this does. A second copy of the shaping is a second body format, and
 * the two would differ by a field nobody notices until a rebuild is no longer byte-equal.
 *
 * @param {object} row @param {number|null|undefined} seq @returns {Readonly<object>}
 */
export function bodyRow(row, seq) {
  const out = {};
  for (const key of Object.keys(row).sort()) {
    if (key === ORDERING_FIELD || key === WALL_CLOCK_FIELD) continue;
    out[key] = row[key];
  }
  // `seq` is the log's total order and is a fact about the portfolio, so it stays. The wall
  // clock is a reading of a clock and D-2 confines it to the freshness block, so it goes -
  // and W6's purity lint refuses the body outright if it ever comes back.
  out[ORDERING_FIELD] = seq === null || seq === undefined ? null : Number(seq);
  return Object.freeze(out);
}

/**
 * Derive the row for one discovered file and reconcile it with what the log already carries.
 *
 * The derivation is `deriveRow` - the same function object the W9 write path calls - so the
 * two paths cannot fork. What this function adds is the LOG's two facts: the `seq` the event
 * was recorded at, and the lineage it supersedes. When the log's row for these exact bytes
 * exists, its seq and lineage are adopted; when it does not, the seq is null (this file is
 * durable on disk and not yet in the log - the W8 sweep's job, not the rebuilder's, because a
 * rebuild that appended could not be byte-equal to itself).
 *
 * @param {{class: string, project_id: string, root: string, rel: string, bytes: Buffer,
 *          record?: object|null, history?: ReadonlyArray<object>}} req
 * @returns {Readonly<{row: object, seq: number|null, indexed: boolean, fork: object|null}>}
 */
export function deriveDiscoveredRow(req) {
  const history = req.history ?? [];
  const latest = history.length > 0 ? history[history.length - 1] : null;
  const matched = latest !== null && latest.sha256 === hashBytes(req.bytes);

  const supersedes = matched
    ? (latest.supersedes === undefined ? null : latest.supersedes)
    : (latest === null ? null : Number(latest[ORDERING_FIELD]));

  const derived = deriveRow(req.class, req.project_id, req.rel, req.bytes, {
    supersedes,
    record: req.record,
  });

  // THE ANTI-FORK CHECK, made in the product rather than only in a test. If the bytes are the
  // ones the log recorded, the row derived here must be the row the log carries, field for
  // field. A difference means the two producers have diverged - which is the one thing the
  // shared derivation exists to make impossible - so it is recorded loudly instead of being
  // resolved in favour of whichever side ran last.
  let fork = null;
  if (matched && rowFingerprint(latest) !== rowFingerprint(derived)) {
    fork = Object.freeze({
      project_id: req.project_id,
      class: req.class,
      path: req.rel,
      seq: Number(latest[ORDERING_FIELD]),
      log_fingerprint: rowFingerprint(latest),
      rebuilt_fingerprint: rowFingerprint(derived),
    });
  }

  return Object.freeze({
    row: derived,
    seq: matched ? Number(latest[ORDERING_FIELD]) : null,
    indexed: matched,
    fork,
  });
}

// -- the rebuild ---------------------------------------------------------------

/**
 * Rebuild the portfolio state from input set I. No bytes are written here: this is the
 * function that turns I into `{body, freshness}` plus the report of everything it found, and
 * `rebuildIndex` below is what makes those bytes durable.
 *
 * Splitting the two is what makes the shuffled-replay leg possible: the same input with its
 * events in a different order must produce the same `body`, and that is checkable without
 * touching a disk twice.
 *
 * @param {{events?: ReadonlyArray<object>, paths?: object, head_seq?: number,
 *          head_sha256?: string|null, fsx?: object}} input
 * @param {{fsx?: object, now?: number|Date, maxEntries?: number, readdir?: Function,
 *          excludeDirNames?: ReadonlyArray<string>,
 *          candidates?: Record<string, ReadonlyArray<string>>, hostname?: string}} [opts]
 * @returns {Readonly<object>}
 */
export function rebuildSnapshot(input, opts = {}) {
  const fsx = opts.fsx ?? input.fsx ?? fs;
  // Replayed in `seq` order HERE, once, so nothing downstream depends on the order the events
  // arrived in. That is the whole of the order-independence property: NG-4 says `seq` is the
  // sole total order, so a shuffled input is the same input.
  const events = replayEvents(Array.isArray(input.events) ? input.events : []);
  const view = materializeRegistry(events);
  const rowsByIdentity = derivedRowsInLog(events);
  const at = new Date(opts.now ?? Date.now()).toISOString();

  const identity = classifyIdentityPass(view.projects, { fsx, candidates: opts.candidates });

  const projects = [];
  const rows = [];
  const unparseable = [];
  const unclassified = [];
  const hazards = [];
  const conflicts = [];
  const refused = [];
  const retained = [];
  const unknown = [];
  const forks = [];
  const notices = [];
  const perProject = {};
  const perClassDiscovered = Object.fromEntries(DERIVABLE_CLASSES.map((c) => [c, 0]));

  let discovered = 0;
  let walkFiles = 0;
  let refusedDiscovery = 0;
  let parsed = 0;
  let markers = 0;
  let live = 0;
  let replayed = 0;
  const seenIdentities = new Set();

  for (const project of view.projects) {
    const id = project.project_id;
    const root = project.current_path;
    const binding = identity.byId.get(id) ?? null;
    const conflicted = binding !== null && binding.binding === BINDING.CONFLICT;

    projects.push(Object.freeze({
      project_id: id,
      registered_path: project.root,
      current_path: root,
      marker_sha256: project.marker_sha256,
      registered_seq: project.registered_seq,
      // NOTE what is NOT here: presence, freshness, last_seen. Those are answers about the
      // filesystem at this instant, and D-2 puts every such answer in the freshness block.
    }));

    if (conflicted) {
      // NG-3. The project is counted exactly once (it is one entry in `projects`), NEITHER
      // path is bound, no id is minted, and nothing is ingested from either directory: a
      // clone that silently won would inherit the original's history, and a clone that
      // silently lost would evaporate the operator's work.
      conflicts.push(Object.freeze({
        project_id: id,
        paths: Object.freeze([...binding.paths]),
        status: assertStatusCode(INTEGRITY.IDENTITY_CONFLICT, 'rebuild identity conflict'),
      }));
      notices.push(rebuildOutcome(REBUILD_CODE.IDENTITY_CONFLICT, {
        project_id: id,
        path: binding.paths[0],
        other_path: binding.paths[1],
      }));
      const replayedHere = replayLogRows(id, project, rowsByIdentity, {
        rows,
        retained,
        refused,
        notices,
        seenIdentities,
        reason: INTEGRITY.IDENTITY_CONFLICT,
        presence: PRESENCE.LIVE,
      });
      replayed += replayedHere;
      perProject[id] = perProjectFreshness({
        last_seen: at,
        last_verified: null,
        presence: PRESENCE.LIVE,
        freshness: FRESHNESS.UNKNOWN,
      });
      continue;
    }

    // W11's classifier runs BEFORE the walk, because ABSENT and UNREACHABLE are different
    // answers and only one of the three presences is worth walking. A root that is gone has
    // nothing to walk; a root that stats fine and cannot be listed - a denied ACL, a cloud
    // placeholder that was never hydrated, a share whose host stopped answering - must be
    // reported as unopenable rather than as empty, and a walk that returned no files would
    // report exactly the wrong one of those two.
    const probed = classifyRootStatus(root, {
      fsx,
      attributesOf: opts.attributesOf,
      probeListing: opts.probeListing,
    });

    // `readdir` is W2's injection seam, forwarded rather than swallowed. Two of the three NG-2
    // path hazards cannot be manufactured on an ordinary Windows host - it will not create two
    // entries differing only by case, and a junction may be refused - so a rebuilder that did
    // not forward the seam would leave those hazard rows untestable through the real verb.
    const found = probed.live
      ? discoverRoot(root, {
        fsx,
        maxEntries: opts.maxEntries,
        readdir: opts.readdir,
        excludeDirNames: opts.excludeDirNames,
      })
      : null;

    const rootAbs = found === null ? probed.root : found.root;
    // Hazard parity, stated rather than assumed: an unreachable root IS a walk hazard, and
    // skipping the walk must not skip the hazard row. The synthetic entry is the one
    // walkRoot would have produced, fed through the same loop so there is one formatting.
    const walkHazards = found !== null
      ? found.hazards
      : (probed.unreachable
        ? [{ code: HAZARD.UNREACHABLE, path: '.', skipped: true, detail: probed.reason }]
        : []);

    for (const hazard of walkHazards) {
      const rowCode = hazardRowFor(hazard.code);
      hazards.push(Object.freeze({
        project_id: id,
        hazard: hazard.code,
        code: rowCode,
        path: toPosix(String(hazard.path ?? '.')),
        target: hazard.target ?? null,
        skipped: hazard.skipped === true,
      }));
      if (rowCode !== null) {
        notices.push(rebuildOutcome(rowCode, {
          path: path.join(rootAbs, String(hazard.path ?? '.')),
          other_path: (hazard.peers ?? []).join(', '),
          target: hazard.target ?? '',
          cap: hazard.cap ?? CAPS.walk_entries,
          errno: hazard.detail ?? '',
        }));
      }
    }

    // The walk is the LATER observation, so when it disagrees with the probe - a root can
    // vanish between the two, and on a flaky share it will - the walk wins. Its verdict is
    // expressed in the classifier's shape rather than in a second shape of the rebuilder's
    // own, so exactly one module decides what a non-live root is.
    const status = found === null || found.presence === PRESENCE.LIVE
      ? probed
      : rootStatusOf(found.root, found.presence, found.reason);

    if (!status.live) {
      // A non-live root contributes its DERIVED rows from the log and nothing from a disk
      // nobody could read. The rows are RETAINED: absence changes presence and freshness, and
      // never the retained set.
      notices.push(rebuildOutcome(
        status.absent ? REBUILD_CODE.ROOT_ABSENT : REBUILD_CODE.ROOT_UNREACHABLE,
        { path: root, project_id: id, errno: status.reason ?? '' },
      ));

      // THE LOUD UNKNOWN (W11). One explicit row, reconstructed from the NATIVE registration
      // and reconcile events alone: project_id, the registered path, the registration receipt
      // id, and the last-known path. It reads NOTHING from the missing root, which is the only
      // reason a row can exist at all for the project that can supply nothing - and it is what
      // keeps the portfolio from shrinking by one with no line of output being wrong.
      unknown.push(unknownRowFromNative(project, status));

      const replayedHere = replayLogRows(id, project, rowsByIdentity, {
        rows,
        retained,
        refused,
        notices,
        seenIdentities,
        reason: status.presence,
        presence: status.presence,
      });
      replayed += replayedHere;
      perProject[id] = perProjectFreshness({
        last_seen: null,
        last_verified: null,
        presence: status.presence,
        freshness: status.freshness,
      });
      continue;
    }

    live += 1;
    let behind = 0;

    for (const file of found.files) {
      walkFiles += 1;

      if (!file.contained) {
        refusedDiscovery += 1;
        refused.push(Object.freeze({
          project_id: id,
          class: file.class,
          path: file.rel,
          status: assertStatusCode(INTEGRITY.TAMPERED, 'rebuild discovery escape'),
          code: REBUILD_CODE.PATH_ESCAPE,
        }));
        notices.push(file.outcome);
        // Refused at the boundary, BEFORE it becomes an input, so it is deliberately not one
        // of `discovered`'s three outcomes - it never entered classification at all. It is
        // counted in `refused` and in `walk_files`, and `walk_files == discovered + refused`
        // is asserted alongside the totality equation, so nothing is invisible either way.
        continue;
      }

      discovered += 1;

      if (file.class === null) {
        unclassified.push(Object.freeze({
          project_id: id,
          path: file.rel,
          status: assertStatusCode(INTEGRITY.UNCLASSIFIED, 'rebuild unclassified'),
          code: REBUILD_CODE.UNCLASSIFIED,
        }));
        notices.push(rebuildOutcome(REBUILD_CODE.UNCLASSIFIED, { path: file.rel }));
        continue;
      }

      if (!file.readable) {
        // UNREADABLE is a finding, not an absence. Counting it as unparseable keeps the
        // equation total, and the reason says exactly which kind of failure it was.
        unparseable.push(unparseableRow(id, file.class, file.rel, PARSE_REASON.UNREADABLE));
        if (DERIVABLE_CLASSES.includes(file.class)) {
          notices.push(rebuildOutcome(
            rebuildClassCode(REBUILD_CLASS_STEM.UNPARSEABLE, file.class),
            { path: file.rel, reason: `${PARSE_REASON.UNREADABLE}: ${file.errno}` },
          ));
        }
        continue;
      }

      if (file.class === CLASS.IDENTITY_MARKER) {
        // The marker is discovered, parsed and counted - it is a file under a registered root
        // and the equation covers every one of those - but it never becomes a content row.
        // It is the NATIVE mirror of an identity the log already carries, and a content row
        // derived from it would put membership in two stores.
        const check = parseBytes(CLASS.IDENTITY_MARKER, file.bytes, { path: file.abs });
        if (check.ok) {
          parsed += 1;
          markers += 1;
        } else {
          unparseable.push(unparseableRow(id, file.class, file.rel, check.reason ?? PARSE_REASON.UNKNOWN_CLASS));
        }
        continue;
      }

      perClassDiscovered[file.class] += 1;
      const source = sourceRecordFor(file.class, file.bytes, file.abs);
      if (!source.ok) {
        const reason = source.reason ?? PARSE_REASON.INVALID_JSON;
        unparseable.push(unparseableRow(id, file.class, file.rel, reason));
        const stem = PARSE_REASON_STEM[reason] ?? REBUILD_CLASS_STEM.UNPARSEABLE;
        notices.push(rebuildOutcome(rebuildClassCode(stem, file.class), {
          path: file.rel,
          reason: source.detail === null ? reason : `${reason}: ${source.detail}`,
          offset: 0,
        }));
        continue;
      }

      const identityKey = rowIdentity({ project_id: id, class: file.class, path: file.rel });
      seenIdentities.add(identityKey);
      const outcome = deriveDiscoveredRow({
        class: file.class,
        project_id: id,
        root: found.root,
        rel: file.rel,
        bytes: file.bytes,
        record: source.record,
        history: rowsByIdentity.get(identityKey) ?? [],
      });
      if (outcome.fork !== null) forks.push(outcome.fork);
      if (!outcome.indexed) behind += 1;
      rows.push(bodyRow(outcome.row, outcome.seq));
      parsed += 1;
    }

    // Rows the log carries for this LIVE root whose file is no longer on disk. Retained and
    // named: removal is nobody's, and a swept-away row is the silent shrink the North Star
    // forbids.
    replayed += replayLogRows(id, project, rowsByIdentity, {
      rows,
      retained,
      refused,
      notices,
      seenIdentities,
      reason: FRESHNESS.UNKNOWN,
      presence: PRESENCE.LIVE,
      onlyMissing: true,
    });

    perProject[id] = perProjectFreshness({
      last_seen: at,
      last_verified: null,
      presence: PRESENCE.LIVE,
      freshness: behind > 0 ? FRESHNESS.STALE : FRESHNESS.FRESH,
    });
  }

  for (const className of DERIVABLE_CLASSES) {
    if (perClassDiscovered[className] === 0) {
      // EMPTY is its own row and is not UNKNOWN: the steward looked at every live root and
      // there genuinely are no files of this class.
      notices.push(rebuildOutcome(
        rebuildClassCode(REBUILD_CLASS_STEM.EMPTY, className),
        {},
        { ok: true },
      ));
    }
  }

  if (view.projects.length === 0) {
    notices.push(rebuildOutcome(REBUILD_CODE.NO_PROJECTS, { home: input.paths?.home ?? '' }, { ok: true }));
  }

  const counts = {
    projects: view.projects.length,
    live,
    walk_files: walkFiles,
    discovered,
    parsed,
    unparseable: unparseable.length,
    unclassified: unclassified.length,
    rows: rows.length,
    markers,
    replayed,
    // The loud unknowns are COUNTED, not merely rendered. A count of absent roots that only
    // exists as a line of text is a count nothing can assert on.
    unknown: unknown.length,
    non_live: unknown.length,
    refused: refused.length,
    refused_discovery: refusedDiscovery,
    refused_replay: refused.length - refusedDiscovery,
    conflicts: conflicts.length,
    hazards: hazards.length,
  };

  const body = {
    version: REBUILD_VERSION,
    inventory_version: INVENTORY_VERSION,
    projects,
    rows,
    // W14's tamper baseline, and the reason it sits in `body`: it is a pure function of the
    // rows above, so it survives a delete-and-rebuild byte for byte. `steward verify` asks
    // this ONE question per project before it opens a single file.
    content_hashes: contentHashesFor(rows),
    unparseable: sortByJson(unparseable),
    unclassified: sortByJson(unclassified),
    hazards: sortByJson(hazards),
    conflicts: sortByJson(conflicts),
    refused: sortByJson(refused),
    retained: sortByJson(retained),
    // In `body` rather than in the report, deliberately: the unknown row is portfolio CONTENT
    // - it is the project, as much as a live project's rows are - so it belongs to the region
    // byte-equality is asserted over. A row that lived only in a receipt would disappear the
    // moment somebody read the snapshot instead of the run that produced it, which is the
    // silent shrink wearing a different hat.
    unknown: sortUnknownRows(unknown),
    forks: sortByJson(forks),
    counts,
  };

  const freshness = emptyFreshnessBlock({
    head_seq: Number(input.head_seq ?? view.head_seq ?? 0),
    head_sha256: input.head_sha256 === undefined ? logHeadSha256(events) : input.head_sha256,
    computed_at: at,
    per_project: perProject,
  });

  const canonical = serializeSnapshot({ schema: SNAPSHOT_SCHEMA, body, freshness }, opts);
  const totality = totalityOf(counts);

  return Object.freeze({
    ok: true,
    version: REBUILD_VERSION,
    body,
    freshness,
    canonical,
    totality,
    counts: Object.freeze(counts),
    view,
    identity: identity.classification,
    project_count: countProjects(identity.classification),
    notices: Object.freeze(notices),
    conflicts: Object.freeze(conflicts),
    refused: Object.freeze(refused),
    forks: Object.freeze(forks),
    retained: Object.freeze(retained),
    unknown: sortUnknownRows(unknown),
    unparseable: Object.freeze(unparseable),
    unclassified: Object.freeze(unclassified),
    hazards: Object.freeze(hazards),
  });
}

/** @param {string} id @param {string} className @param {string} rel @param {string} reason */
function unparseableRow(id, className, rel, reason) {
  return Object.freeze({
    project_id: id,
    class: className,
    // reason AND path, exactly as the contract words it: an UNPARSEABLE row that does not say
    // which file or why is a count, not a report.
    path: rel,
    reason,
    status: assertStatusCode(
      reason === PARSE_REASON.MOJIBAKE ? INTEGRITY.MOJIBAKE : INTEGRITY.UNPARSEABLE,
      'rebuild unparseable',
    ),
  });
}

/**
 * Replay the DERIVED rows the log carries for one project.
 *
 * Every replayed path is contained first. A recorded path that escapes its registered root is
 * refused as TAMPERED and its content is NEVER ingested - which is the case a tampered log
 * would produce, and the reason containment is checked on the replay path and not only on the
 * discovery path.
 *
 * @param {string} id @param {object} project @param {Map<string, object[]>} rowsByIdentity
 * @param {{rows: Array<object>, retained: Array<object>, refused: Array<object>,
 *          notices: Array<object>, seenIdentities: Set<string>, reason: string,
 *          presence?: string, onlyMissing?: boolean}} sink
 * @returns {number} how many rows were replayed
 */
function replayLogRows(id, project, rowsByIdentity, sink) {
  let count = 0;
  // W11: every replayed row carries the presence of the root it came from and the freshness
  // that follows from it. Nobody read these bytes this pass - for a non-live root nobody
  // COULD - so the row is retained and its freshness says so, which is the whole of what
  // absence is allowed to change.
  const presence = sink.presence ?? PRESENCE.LIVE;
  const freshness = replayedRowFreshness(presence);
  // Sorted by IDENTITY, explicitly: the replay order decides the order rows are pushed, and a
  // default sort over [key, value] pairs is a sort over stringified objects, which is a
  // determinism claim resting on a coincidence.
  const entries = [...rowsByIdentity.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  for (const [identityKey, history] of entries) {
    const latest = history[history.length - 1];
    if (latest.project_id !== id) continue;
    // A row whose file was discovered on a live root has already been derived from the bytes
    // on disk, and the disk is the source of truth. Replaying it too would put the same
    // identity in the body twice.
    if (sink.seenIdentities.has(identityKey)) continue;

    const contained = containedPath(project.current_path, latest.path);
    if (!contained.ok) {
      sink.refused.push(Object.freeze({
        project_id: id,
        class: latest.class,
        path: latest.path,
        seq: Number(latest[ORDERING_FIELD]),
        status: assertStatusCode(INTEGRITY.TAMPERED, 'rebuild replay escape'),
        code: REBUILD_CODE.PATH_ESCAPE,
      }));
      sink.notices.push(contained.outcome);
      sink.seenIdentities.add(identityKey);
      continue;
    }

    sink.seenIdentities.add(identityKey);
    sink.rows.push(bodyRow(latest, latest[ORDERING_FIELD]));
    sink.retained.push(Object.freeze({
      project_id: id,
      class: latest.class,
      path: latest.path,
      seq: Number(latest[ORDERING_FIELD]),
      reason: sink.reason,
      presence,
      freshness,
    }));
    if (DERIVABLE_CLASSES.includes(latest.class)) {
      sink.notices.push(rebuildOutcome(
        rebuildClassCode(REBUILD_CLASS_STEM.RETAINED_UNKNOWN, latest.class),
        { path: latest.path, project_id: id },
      ));
    }
    count += 1;
  }
  return count;
}

/**
 * Sort a report array by its canonical text.
 *
 * The arrays under `projects` and `rows` are ordered by the serializer (W6 owns those two
 * comparators). Every other array here has no frozen comparator, so it is ordered by its own
 * content - which is total, and therefore deterministic, without a sort key per array shape.
 *
 * @param {Array<object>} list @returns {ReadonlyArray<object>}
 */
function sortByJson(list) {
  return Object.freeze(
    [...list].sort((a, b) => {
      const x = JSON.stringify(a);
      const y = JSON.stringify(b);
      return x < y ? -1 : x > y ? 1 : 0;
    }),
  );
}

// -- the verb ------------------------------------------------------------------

/**
 * `steward rebuild`.
 *
 * Read the log (and only the log), discover the live roots, replay through canonical.mjs, and
 * replace the snapshot through the D-1 temp+rename primitive.
 *
 * THE LOCK IS TAKEN TWICE, ON PURPOSE. Once to read the log to a known head, and once to make
 * the new snapshot durable - never across the walk in between. Holding the portfolio lock for
 * the length of a full portfolio walk would starve every writer past the W5 starvation bound,
 * which is exactly the "a rebuild blocks the steward" failure the bound exists to prevent.
 * Events appended during the walk are not lost and are not silently missed: the snapshot
 * records the head it derived FROM, and the D-3 tail merge answers for everything after it.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number|Date,
 *          maxEntries?: number, readdir?: Function, boundMs?: number, staleMs?: number,
 *          quarantine?: boolean, candidates?: Record<string, ReadonlyArray<string>>,
 *          write?: boolean, retries?: number, lockOpts?: object, hostname?: string,
 *          pid?: number}} [opts]
 * @returns {Readonly<object>} the rebuild-receipt-v1
 */
export function rebuildIndex(opts = {}) {
  const paths = indexPathsFrom(opts);
  const input = readRebuildInput({ ...opts, paths });

  if (input.ok !== true) {
    return Object.freeze({
      ok: false,
      schema: REBUILD_RECEIPT_SCHEMA,
      version: REBUILD_VERSION,
      home: paths.home,
      log: paths.log,
      snapshot: paths.snapshot,
      outcome: input.outcome,
      input: Object.freeze({
        snapshot_read: false,
        head_seq: input.head_seq ?? 0,
        index_home_reads: Object.freeze([...input.journal.reads]),
        refused_reads: Object.freeze([...input.journal.refused]),
      }),
      body: null,
      freshness: null,
      canonical: null,
      totality: null,
      report: null,
      write: null,
    });
  }

  const built = rebuildSnapshot(
    {
      events: input.events,
      paths,
      head_seq: input.head_seq,
      head_sha256: input.head_sha256,
    },
    { ...opts, fsx: input.fsx },
  );

  const notices = [...built.notices];
  if (input.torn !== null && input.torn !== undefined) notices.push(input.torn);
  for (const hazard of input.blocking_hazards ?? []) notices.push(hazard);

  let write = null;
  if (opts.write !== false) {
    write = withPortfolioLock(
      paths,
      () =>
        writeCanonicalSnapshot(
          paths.snapshot,
          { schema: SNAPSHOT_SCHEMA, body: built.body, freshness: built.freshness },
          {
            // The RAW fs here, not the input-only facade: the facade exists to keep the
            // snapshot out of the INPUT set, and the writer is the one caller whose whole job
            // is to replace it.
            fsx: opts.fsx,
            seq: input.head_seq,
            pid: opts.pid,
            retries: opts.retries,
            hostname: opts.hostname,
          },
        ),
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        lockOpts: opts.lockOpts,
      },
    );
    if (write.ok !== true) {
      return Object.freeze({
        ok: false,
        schema: REBUILD_RECEIPT_SCHEMA,
        version: REBUILD_VERSION,
        home: paths.home,
        log: paths.log,
        snapshot: paths.snapshot,
        outcome: rebuildOutcome(REBUILD_CODE.INDEX_UNWRITABLE, {
          path: paths.snapshot,
          errno: write.detail?.errno ?? write.code ?? '',
        }),
        input: inputReceipt(input),
        body: built.body,
        freshness: built.freshness,
        canonical: built.canonical,
        totality: built.totality,
        report: reportOf(built, notices),
        write,
      });
    }
  }

  return Object.freeze({
    ok: true,
    schema: REBUILD_RECEIPT_SCHEMA,
    version: REBUILD_VERSION,
    home: paths.home,
    log: paths.log,
    snapshot: paths.snapshot,
    outcome: rebuildOutcome(REBUILD_OK, {
      projects: built.counts.projects,
      live: built.counts.live,
      discovered: built.counts.discovered,
      parsed: built.counts.parsed,
      unparseable: built.counts.unparseable,
      unclassified: built.counts.unclassified,
      replayed: built.counts.replayed,
    }),
    input: inputReceipt(input),
    body: built.body,
    freshness: built.freshness,
    canonical: built.canonical,
    body_text: built.canonical.body_text,
    sha256: built.canonical.sha256,
    totality: built.totality,
    report: reportOf(built, notices),
    write,
  });
}

/** @param {object} input @returns {Readonly<object>} what the receipt says about input set I */
function inputReceipt(input) {
  return Object.freeze({
    set: REBUILD_INPUT,
    excluded: REBUILD_EXCLUDED_INPUT,
    snapshot_read: false,
    head_seq: input.head_seq,
    head_sha256: input.head_sha256 ?? null,
    event_count: input.events.length,
    // Every read this rebuild made inside the index home, and every read it REFUSED. The
    // claim "the rebuilder never opened the old snapshot" is checkable from this list.
    index_home_reads: Object.freeze([...input.journal.reads]),
    refused_reads: Object.freeze([...input.journal.refused]),
    total_reads: input.journal.total,
  });
}

/** @param {object} built @param {Array<object>} notices @returns {Readonly<object>} */
function reportOf(built, notices) {
  return Object.freeze({
    counts: built.counts,
    totality: built.totality,
    projects: built.view.projects,
    identity: built.identity,
    project_count: built.project_count,
    conflicts: built.conflicts,
    refused: built.refused,
    retained: built.retained,
    unknown: built.unknown,
    unparseable: built.unparseable,
    unclassified: built.unclassified,
    hazards: built.hazards,
    forks: built.forks,
    notices: Object.freeze(notices),
    codes: Object.freeze([...new Set(notices.map((n) => n.code).filter((c) => typeof c === 'string'))].sort()),
  });
}

/**
 * Compare two snapshot artifacts the way D-2 permits and no further: `body` byte for byte,
 * and the freshness block field-wise against its frozen field set.
 *
 * It lives in the product rather than in a test because it is the CONTRACT, and a contract
 * that only exists inside one assertion is a contract the next wave re-invents slightly
 * differently.
 *
 * @param {string} leftText @param {string} rightText canonical snapshot texts
 * @returns {Readonly<{body_equal: boolean, freshness_fields_equal: boolean,
 *          differences: ReadonlyArray<string>}>}
 */
export function compareSnapshotTexts(leftText, rightText) {
  const left = splitCanonicalText(leftText);
  const right = splitCanonicalText(rightText);
  const differences = [];
  if (left.body_text !== right.body_text) differences.push(BYTE_EQUAL_REGION);
  if (left.schema !== right.schema) differences.push('schema');

  const frozen = [...FRESHNESS_KEYS].sort().join(',');
  const perFrozen = [...PER_PROJECT_KEYS].sort().join(',');
  const blocks = [JSON.parse(left.freshness_text), JSON.parse(right.freshness_text)];
  let fieldsEqual = true;

  // FIELD-WISE against the FROZEN set, not merely field-wise against each other. Two blocks
  // that carried the same extra key would agree with each other and still be outside D-2, so
  // the comparison is against W4's closed field list on both sides.
  for (const block of blocks) {
    if (Object.keys(block).sort().join(',') !== frozen) {
      fieldsEqual = false;
      differences.push('freshness field set');
      continue;
    }
    for (const id of Object.keys(block.per_project ?? {})) {
      if (Object.keys(block.per_project[id]).sort().join(',') !== perFrozen) {
        fieldsEqual = false;
        differences.push(`freshness.per_project.${id} field set`);
      }
    }
  }

  return Object.freeze({
    body_equal: left.body_text === right.body_text,
    freshness_fields_equal: fieldsEqual,
    differences: Object.freeze([...new Set(differences)]),
  });
}

/** Re-exported so a caller needs one import to check the rows a rebuild produced. */
export { isDerivedEvent, rowFingerprint, rowIdentity };

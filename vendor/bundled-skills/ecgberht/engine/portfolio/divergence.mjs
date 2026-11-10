/**
 * W8 - the startup divergence sweep: the repair for the crash window W9's ordering leaves.
 *
 * THE WINDOW THIS EXISTS FOR. The frozen success ordering is: the source of truth is
 * written and fsynced -> the project lock is released -> the DERIVED event is appended and
 * fsynced to the ONE log -> the verb returns success. Between the first step and the third
 * there is a moment where the receipt (or instrument, or roadmap event) is durable on disk
 * and the index knows nothing about it. That window cannot be closed: it is two files, on
 * two paths, and one power cut. Pretending otherwise - by appending first, or by writing
 * both under one lock - either indexes files that do not exist or reintroduces the ABBA
 * deadlock engine/portfolio/lock-order.mjs forbids.
 *
 * So the window is not closed; it is SWEPT. On start, every live registered root is walked
 * through the inventory-v1 discovery paths, every discovered file is hashed, and every file
 * whose DERIVED row is missing from the log - or whose row records different bytes - has a
 * row regenerated from the file that survived. The crash costs a moment of staleness and no
 * row at all, which is exactly what C2 asks for.
 *
 * WHY THE REGENERATED ROW MUST BE BYTE-IDENTICAL TO THE WRITE PATH'S. If the sweep derived
 * rows its own way, a portfolio would carry two shapes of the same fact and the W10
 * byte-equal rebuild would be impossible to hold: rows written by a lucky process would
 * differ from rows written by an unlucky one. So there is ONE derivation, `deriveRow`, and
 * both paths call it. W9 landed engine/portfolio/derive.mjs as the permanent home of that
 * function, exactly as this header said it would; this module now IMPORTS it (and re-exports
 * it under its W8 name so existing callers are undisturbed) and still takes it by injection
 * (`opts.deriveRow`) for the tests that drive the seam. A re-export cannot fork; a second
 * copy would - test/w51-kill-window.test.mjs is what proves the property rather than
 * asserting it: it kills a child between the two steps and compares the swept row to the
 * row an uncrashed run produced, field for field, byte for byte.
 *
 * THE ORPHAN TEMP. The D-1 snapshot write is temp -> fsync -> rename. A process killed
 * between the temp and the rename leaves `<snapshot>.tmp-<pid>-<seq>` behind holding a
 * partial or complete document nobody renamed. The previous snapshot is untouched and
 * remains the authoritative one, and the orphan is NEVER read: it is not a name any reader
 * resolves (home.mjs names exactly two files), and this sweep removes it and counts it.
 * `authoritativeIndexFiles()` states that closed set in code so a future reader cannot
 * quietly widen it.
 *
 * WHAT THIS MODULE NEVER DOES. It never deletes a row, never rebinds an identity, and never
 * writes the snapshot - it appends DERIVED events to the log through the W5 primitive and
 * nothing else. A row whose file has vanished is REPORTED, never removed: retention on an
 * absent root is W11's, and a sweep that pruned rows would be the silent shrink the North
 * Star forbids.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import { appendEvents, indexPathsFrom, openIndexForRead, ORDERING_FIELD } from '../append-log.mjs';
import {
  DERIVABLE_CLASSES,
  DERIVED_EVENT_TYPE,
  DERIVED_ROW_FIELDS,
  DERIVED_ROW_VERSION,
  PROJ_FIELDS,
  PROJ_TRUNCATED_FIELD,
  capProjValue,
  deriveRow,
  derivedRowFrom,
  derivedRowsInLog,
  isDerivedEvent,
  projectionFor,
  rowFingerprint,
  rowIdentity,
  sourceRecordFor,
} from './derive.mjs';
import { hashBytes } from './commit-intent.mjs';
import { rowOutcome } from './failure-tables.mjs';
import {
  openablePath,
  toPosix,
  walkRoot,
} from './inventory.mjs';
import { assertPortfolioLockPermitted } from './lock-order.mjs';
import { materializeRegistry } from './registry.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The sweep's frozen version. Changing the regenerated row shape means divergence-v2. */
export const DIVERGENCE_VERSION = 'divergence-v1';

/** The receipt this sweep emits to its caller. */
export const DIVERGENCE_RECEIPT_SCHEMA = 'divergence-sweep-v1';

/**
 * The derived-row-v1 vocabulary, re-exported from its permanent home so every caller that
 * learned these names from the sweep keeps them and NOBODY gets a second copy. W9's
 * derive.mjs is the definition; this line is a pointer to it.
 */
export {
  DERIVABLE_CLASSES,
  DERIVED_EVENT_TYPE,
  DERIVED_ROW_FIELDS,
  DERIVED_ROW_VERSION,
  PROJ_FIELDS,
  PROJ_TRUNCATED_FIELD,
  capProjValue,
  deriveRow,
  derivedRowFrom,
  derivedRowsInLog,
  isDerivedEvent,
  projectionFor,
  rowFingerprint,
  rowIdentity,
  sourceRecordFor,
};

/** How a discovered file compares against the rows the log already carries. */
export const DIVERGENCE = Object.freeze({
  MATCHED: 'MATCHED',
  ROW_MISSING: 'ROW_MISSING',
  ROW_STALE: 'ROW_STALE',
  FILE_UNPARSEABLE: 'FILE_UNPARSEABLE',
  FILE_UNREADABLE: 'FILE_UNREADABLE',
  ROW_WITHOUT_FILE: 'ROW_WITHOUT_FILE',
});

/** The verdicts that cause a row to be regenerated. Everything else is reported only. */
export const REGENERATED_VERDICTS = Object.freeze([DIVERGENCE.ROW_MISSING, DIVERGENCE.ROW_STALE]);

/** The sweep's own outcome codes, with the sentence an operator reads. */
export const SWEEP_CODE = Object.freeze({
  CLEAN: 'DIVERGENCE_SWEEP_CLEAN',
  REPAIRED: 'DIVERGENCE_SWEEP_REPAIRED',
  INDEX_UNREADABLE: 'DIVERGENCE_INDEX_UNREADABLE',
  APPEND_FAILED: 'INGEST_APPEND_FAILED',
});

/** @type {Readonly<Record<string, {status: string, text: string}>>} */
export const SWEEP_ROWS = Object.freeze({
  [SWEEP_CODE.CLEAN]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'divergence CLEAN'),
    text:
      'The startup divergence sweep compared {files} discovered file(s) across {projects} live '
      + 'root(s) against the index and found every DERIVED row present with matching bytes. '
      + '{temps} orphan temp file(s) were swept.',
  }),
  [SWEEP_CODE.REPAIRED]: Object.freeze({
    status: assertStatusCode(FRESHNESS.FRESH, 'divergence REPAIRED'),
    text:
      'The startup divergence sweep regenerated {regenerated} DERIVED row(s) from files that '
      + 'survived a crash between the source-of-truth write and the index flush, and swept '
      + '{temps} orphan temp file(s). Nothing was removed: {row_without_file} row(s) whose file '
      + 'is no longer present are retained and reported.',
  }),
  [SWEEP_CODE.INDEX_UNREADABLE]: Object.freeze({
    status: assertStatusCode(PRESENCE.UNREACHABLE, 'divergence INDEX_UNREADABLE'),
    text:
      'The startup divergence sweep could not read the index ({reason}), so it repaired '
      + 'nothing. A sweep that guessed at the index would append rows the log may already '
      + 'carry, which is worse than a sweep that refuses.',
  }),
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function sweepOutcome(code, params = {}, extra = {}) {
  // INGEST_APPEND_FAILED is a FROZEN W3 failure row and is read from the table rather than
  // restated here: the sweep's append and the W9 write path's append fail the same way, and
  // two copies of that sentence would drift on the first edit.
  if (code === SWEEP_CODE.APPEND_FAILED) return rowOutcome(code, params, extra);
  const row = SWEEP_ROWS[code];
  if (row === undefined) throw new Error(`divergence: ${code} is not a frozen sweep row`);
  return Object.freeze({
    ok: extra.ok === true,
    code,
    status: row.status,
    text: fill(row.text, params),
    detail: Object.freeze({ ...params }),
  });
}

// -- the authoritative file set ------------------------------------------------

/** The infix the D-1 snapshot temp carries. Read from home.mjs's naming, never re-invented. */
export const TEMP_INFIX = '.tmp-';

/**
 * The ONLY two files a reader may treat as index content.
 *
 * Stated as a closed set rather than as a convention: "no `.tmp-*` file is ever read as
 * authoritative" is a property of the set of names a reader resolves, and a set nothing
 * enumerates is a set that grows.
 *
 * @param {{log: string, snapshot: string}} paths
 * @returns {ReadonlyArray<string>}
 */
export function authoritativeIndexFiles(paths) {
  return Object.freeze([paths.log, paths.snapshot]);
}

/**
 * @param {{log: string, snapshot: string}} paths @param {string} candidate
 * @returns {boolean} whether the candidate is one of the two authoritative files
 */
export function isAuthoritativeIndexFile(paths, candidate) {
  const target = path.resolve(String(candidate));
  return authoritativeIndexFiles(paths).some((p) => path.resolve(p) === target);
}

/**
 * @param {string} name a bare file name inside the index home
 * @param {string} snapshotPath
 * @returns {boolean} whether the name is an orphan snapshot temp
 */
export function isOrphanTempName(name, snapshotPath) {
  return String(name).startsWith(`${path.basename(String(snapshotPath))}${TEMP_INFIX}`);
}

/**
 * Remove every orphan snapshot temp in the index home.
 *
 * A temp is evidence, so it is reported by name and counted; it is removed because leaving
 * it means the next crashed write finds a name collision on its own O_EXCL temp and refuses
 * a snapshot for a reason that has nothing to do with the snapshot.
 *
 * @param {{home: string, snapshot: string}} paths
 * @param {{fsx?: object, remove?: boolean}} [opts]
 * @returns {Readonly<{found: string[], removed: string[], failed: object[]}>}
 */
export function sweepOrphanTemps(paths, opts = {}) {
  const fsx = opts.fsx ?? fs;
  const remove = opts.remove !== false;
  const found = [];
  const removed = [];
  const failed = [];

  let names = [];
  try {
    names = fsx
      .readdirSync(openablePath(paths.home))
      .map((entry) => (typeof entry === 'string' ? entry : entry.name))
      .sort();
  } catch {
    return Object.freeze({ found: Object.freeze([]), removed: Object.freeze([]), failed: Object.freeze([]) });
  }

  for (const name of names) {
    if (!isOrphanTempName(name, paths.snapshot)) continue;
    const abs = path.join(paths.home, name);
    found.push(abs);
    if (!remove) continue;
    try {
      fsx.unlinkSync(openablePath(abs));
      removed.push(abs);
    } catch (err) {
      failed.push(Object.freeze({ path: abs, errno: (err && err.code) || String(err) }));
    }
  }

  return Object.freeze({
    found: Object.freeze(found),
    removed: Object.freeze(removed),
    failed: Object.freeze(failed),
  });
}

// -- the derivation ------------------------------------------------------------
//
// It used to live here. W9 moved it to engine/portfolio/derive.mjs - the permanent home
// this file's header always said it would get - and the names are re-exported above. Nothing
// about the row shape changed in the move, which is the point: the sweep and the W9 write
// path now call literally the same function object, so "the two cannot fork" stops being a
// property somebody has to keep true and becomes a property of the import graph.

// -- discovery -----------------------------------------------------------------

/**
 * Every file under one root that inventory-v1 says is a tracked content class, with its
 * bytes hashed.
 *
 * @param {string} rootAbs
 * @param {{fs?: object, maxEntries?: number}} [opts]
 * @returns {Readonly<{root: string, presence: string, reason: string|null,
 *          files: Array<object>, hazards: ReadonlyArray<object>}>}
 */
export function discoverDerivableFiles(rootAbs, opts = {}) {
  const fsx = opts.fs ?? fs;
  const walk = walkRoot(rootAbs, opts);
  const files = [];

  if (walk.presence !== PRESENCE.LIVE) {
    return Object.freeze({
      root: walk.root,
      presence: walk.presence,
      reason: walk.reason,
      files: Object.freeze([]),
      hazards: Object.freeze(walk.hazards),
    });
  }

  for (const entry of walk.files) {
    if (!DERIVABLE_CLASSES.includes(entry.class)) continue;
    let bytes;
    try {
      // encoding-lint: raw-bytes - the hash must be over the bytes as they are on disk, and
      // MOJIBAKE is a named state that a decoded read erases.
      bytes = fsx.readFileSync(openablePath(entry.abs));
    } catch (err) {
      files.push(Object.freeze({
        class: entry.class,
        rel: toPosix(entry.rel),
        abs: entry.abs,
        bytes: null,
        sha256: null,
        byte_len: null,
        readable: false,
        errno: (err && err.code) || String(err),
      }));
      continue;
    }
    files.push(Object.freeze({
      class: entry.class,
      rel: toPosix(entry.rel),
      abs: entry.abs,
      bytes,
      sha256: hashBytes(bytes),
      byte_len: bytes.length,
      readable: true,
      errno: null,
    }));
  }

  files.sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
  return Object.freeze({
    root: walk.root,
    presence: walk.presence,
    reason: walk.reason,
    files: Object.freeze(files),
    hazards: Object.freeze(walk.hazards),
  });
}

// -- the report ----------------------------------------------------------------

/**
 * Compare every live root's files against the rows the log carries.
 *
 * Reporting is separated from repairing on purpose: `steward doctor` and a dry run want the
 * finding without the append, and a repair whose finding cannot be inspected first is a
 * repair nobody can review.
 *
 * @param {{home?: string, paths?: object, env?: object, fs?: object, fsx?: object,
 *          deriveRow?: Function, maxEntries?: number, boundMs?: number, staleMs?: number}} [opts]
 * @returns {Readonly<object>}
 */
export function divergenceReport(opts = {}) {
  const paths = indexPathsFrom(opts);
  const deriveRow = typeof opts.deriveRow === 'function' ? opts.deriveRow : derivedRowFrom;

  const read = openIndexForRead(opts);
  if (read.ok !== true) {
    return Object.freeze({
      ok: false,
      version: DIVERGENCE_VERSION,
      home: paths.home,
      outcome: sweepOutcome(SWEEP_CODE.INDEX_UNREADABLE, { reason: read.text || read.code }),
      index_outcome: read,
      projects: Object.freeze([]),
      findings: Object.freeze([]),
      regenerable: Object.freeze([]),
      counts: Object.freeze({}),
    });
  }

  const view = materializeRegistry(read.events ?? []);
  const rowsByIdentity = derivedRowsInLog(read.events ?? []);
  const projects = [];
  const findings = [];
  const regenerable = [];
  const seenIdentities = new Set();

  for (const project of view.projects) {
    const discovered = discoverDerivableFiles(project.current_path, opts);
    const perProject = {
      project_id: project.project_id,
      root: discovered.root,
      presence: discovered.presence,
      reason: discovered.reason,
      discovered: discovered.files.length,
      matched: 0,
      regenerated: 0,
      unreadable: 0,
      unparseable: 0,
    };

    for (const file of discovered.files) {
      const identity = rowIdentity({
        project_id: project.project_id,
        class: file.class,
        path: file.rel,
      });
      seenIdentities.add(identity);
      const history = rowsByIdentity.get(identity) ?? [];
      const latest = history.length ? history[history.length - 1] : null;

      if (!file.readable) {
        perProject.unreadable += 1;
        findings.push(Object.freeze({
          verdict: DIVERGENCE.FILE_UNREADABLE,
          status: PRESENCE.UNREACHABLE,
          project_id: project.project_id,
          class: file.class,
          path: file.rel,
          errno: file.errno,
        }));
        continue;
      }

      if (latest !== null && latest.sha256 === file.sha256) {
        perProject.matched += 1;
        findings.push(Object.freeze({
          verdict: DIVERGENCE.MATCHED,
          status: INTEGRITY.OK,
          project_id: project.project_id,
          class: file.class,
          path: file.rel,
          seq: latest[ORDERING_FIELD] ?? null,
        }));
        continue;
      }

      const source = sourceRecordFor(file.class, file.bytes, file.abs);
      if (!source.ok) {
        // Damaged bytes are REPORTED and never regenerated. A row derived from mojibake or
        // from an unparseable file would put a faithful hash of damage into an append-only
        // log, where no later edit removes it.
        perProject.unparseable += 1;
        findings.push(Object.freeze({
          verdict: DIVERGENCE.FILE_UNPARSEABLE,
          status: source.reason === INTEGRITY.MOJIBAKE ? INTEGRITY.MOJIBAKE : INTEGRITY.UNPARSEABLE,
          project_id: project.project_id,
          class: file.class,
          path: file.rel,
          reason: source.reason,
          detail: source.detail,
        }));
        continue;
      }

      const row = deriveRow(file.class, project.project_id, file.rel, file.bytes, {
        supersedes: latest === null ? null : Number(latest[ORDERING_FIELD]),
        record: source.record,
      });
      perProject.regenerated += 1;
      findings.push(Object.freeze({
        verdict: latest === null ? DIVERGENCE.ROW_MISSING : DIVERGENCE.ROW_STALE,
        status: FRESHNESS.STALE,
        project_id: project.project_id,
        class: file.class,
        path: file.rel,
        sha256: file.sha256,
        supersedes: row.supersedes,
      }));
      regenerable.push(row);
    }

    projects.push(Object.freeze(perProject));
  }

  // Rows whose file is gone are retained and named. Removal is not this module's to do -
  // and is nobody's: W11 renders an absent root's rows as unknown, and a swept-away row
  // would be exactly the silent shrink the North Star forbids.
  for (const [identity, history] of [...rowsByIdentity.entries()].sort()) {
    if (seenIdentities.has(identity)) continue;
    const latest = history[history.length - 1];
    findings.push(Object.freeze({
      verdict: DIVERGENCE.ROW_WITHOUT_FILE,
      status: FRESHNESS.UNKNOWN,
      project_id: latest.project_id,
      class: latest.class,
      path: latest.path,
      seq: latest[ORDERING_FIELD] ?? null,
    }));
  }

  const counts = {};
  for (const verdict of Object.values(DIVERGENCE)) counts[verdict] = 0;
  for (const finding of findings) counts[finding.verdict] += 1;

  // Deterministic append order, so two sweeps of one state allocate seqs the same way.
  regenerable.sort((a, b) => {
    const left = `${a.project_id} ${a.class} ${a.path}`;
    const right = `${b.project_id} ${b.class} ${b.path}`;
    return left < right ? -1 : left > right ? 1 : 0;
  });

  return Object.freeze({
    ok: true,
    version: DIVERGENCE_VERSION,
    home: paths.home,
    head_seq: read.head_seq ?? 0,
    outcome: null,
    index_outcome: read,
    projects: Object.freeze(projects),
    findings: Object.freeze(findings),
    regenerable: Object.freeze(regenerable),
    counts: Object.freeze(counts),
  });
}

// -- the sweep -----------------------------------------------------------------

/**
 * The startup sweep: report, regenerate the missing rows, remove the orphan temps.
 *
 * The regenerated rows go out in ONE appendEvents() call: one lock acquisition, one
 * contiguous run of seqs, and - because the primitive reports exactly which seqs became
 * durable - a sweep interrupted halfway is a sweep the next start finishes rather than one
 * that has to be undone.
 *
 * @param {{home?: string, paths?: object, env?: object, fs?: object, fsx?: object,
 *          deriveRow?: Function, apply?: boolean, sweepTemps?: boolean, now?: number}} [opts]
 * @returns {Readonly<object>} the divergence-sweep-v1 receipt
 */
export function sweepDivergence(opts = {}) {
  const paths = indexPathsFrom(opts);
  // The sweep runs at startup, before any verb has taken a project lock. Asserting it here
  // rather than trusting it means a future caller that sweeps from inside a verb finds out
  // at the call site instead of in a deadlock.
  assertPortfolioLockPermitted(paths.log);

  const report = divergenceReport(opts);
  if (report.ok !== true) {
    return Object.freeze({
      ok: false,
      schema: DIVERGENCE_RECEIPT_SCHEMA,
      version: DIVERGENCE_VERSION,
      home: paths.home,
      outcome: report.outcome,
      report,
      regenerated: Object.freeze([]),
      seqs: Object.freeze([]),
      temps: Object.freeze({ found: [], removed: [], failed: [] }),
    });
  }

  const temps = opts.sweepTemps === false
    ? Object.freeze({ found: Object.freeze([]), removed: Object.freeze([]), failed: Object.freeze([]) })
    : sweepOrphanTemps(paths, { fsx: opts.fsx ?? opts.fs });

  const pending = report.regenerable;
  const apply = opts.apply !== false;
  if (!apply || pending.length === 0) {
    return Object.freeze({
      ok: true,
      schema: DIVERGENCE_RECEIPT_SCHEMA,
      version: DIVERGENCE_VERSION,
      home: paths.home,
      outcome: sweepOutcome(
        SWEEP_CODE.CLEAN,
        {
          files: report.counts[DIVERGENCE.MATCHED] + report.counts[DIVERGENCE.ROW_MISSING]
            + report.counts[DIVERGENCE.ROW_STALE],
          projects: report.projects.length,
          temps: temps.removed.length,
        },
        { ok: true },
      ),
      report,
      regenerated: Object.freeze(apply ? [] : pending),
      seqs: Object.freeze([]),
      temps,
    });
  }

  const appended = appendEvents(pending, { ...opts, home: paths.home });
  if (appended.ok !== true) {
    return Object.freeze({
      ok: false,
      schema: DIVERGENCE_RECEIPT_SCHEMA,
      version: DIVERGENCE_VERSION,
      home: paths.home,
      outcome: sweepOutcome(SWEEP_CODE.APPEND_FAILED, {
        path: paths.log,
        reason: appended.text ? appended.text : appended.code,
      }),
      index_outcome: appended,
      report,
      regenerated: Object.freeze(pending),
      seqs: Object.freeze(appended.seqs ?? []),
      temps,
    });
  }

  return Object.freeze({
    ok: true,
    schema: DIVERGENCE_RECEIPT_SCHEMA,
    version: DIVERGENCE_VERSION,
    home: paths.home,
    outcome: sweepOutcome(
      SWEEP_CODE.REPAIRED,
      {
        regenerated: pending.length,
        temps: temps.removed.length,
        row_without_file: report.counts[DIVERGENCE.ROW_WITHOUT_FILE],
      },
      { ok: true },
    ),
    report,
    regenerated: Object.freeze(appended.appended ?? pending),
    seqs: Object.freeze(appended.seqs ?? []),
    head_seq: appended.head_seq,
    temps,
  });
}

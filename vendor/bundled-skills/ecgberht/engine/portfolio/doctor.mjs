/**
 * W19 - `steward doctor`: one pass over the whole health stack, and the ONE honest place to
 * read every detector this engine owns.
 *
 * WHY A VERB AND NOT SEVEN. Every wave before this one shipped a detector and a surface that
 * renders it: W11 knows a root is not there, W14 knows a file drifted, W15 knows an intent is
 * unacknowledged, W16 knows when a copy last left the box, W18 knows how close the log is to
 * its ceiling. Each of those is honest ON ITS OWN SURFACE. What nobody could do before this
 * file existed was ask ONE question - "is this portfolio all right?" - and get an answer that
 * covers all of them, which means the practical answer was whichever detector the operator
 * happened to run. A health stack nobody can read end to end reports green by omission.
 *
 * SEVEN SUBSYSTEMS, ONE LINE EACH. The list is the plan's, in the plan's order:
 * registry/index consistency, ack latency, staleness verify, cap proximity, export-bundle
 * recency, lock-file liveness, marker/identity presence. One line per subsystem, always -
 * including the ones with nothing to report, because a line that only appears when something
 * is wrong is a line whose absence the operator has to interpret.
 *
 * REPORTING ONLY, AND THAT IS A DESIGN DECISION RATHER THAN AN OMISSION. Doctor writes
 * nothing: it does not quarantine a torn tail, does not re-materialize a long tail, does not
 * break a stale lock, does not re-hash a drifted file. The reason is that the one place an
 * operator goes to find out what is true must not be a place that changes what is true while
 * they are looking. Every line therefore names the verb that WOULD act - rebuild, verify,
 * reconcile, export-bundle, compact - and stops there. `WRITES` below is the empty list, as
 * data, so a test can assert the claim rather than read it.
 *
 * THE EXIT CODE IS A LADDER WITH THREE RUNGS, and the top rung is deliberately "could not
 * check" rather than "something is broken": a detector that could not answer hides every
 * other answer behind it, so it outranks a condition the pass actually observed and named.
 *
 * Stdlib only.
 */

import fs from 'node:fs';

import {
  INDEX_READ_CODE,
  indexPathsFrom,
  isProcessAlive,
  openIndexForRead,
  parseLockStamp,
} from '../append-log.mjs';
import { ACK_THRESHOLD_DAYS, durabilityHealth } from './anchor-contract.mjs';
import { EXPORT_VERB, exportRecency } from './bundle.mjs';
import { CAPS, CAP_LEVEL, capStatusFor } from './caps.mjs';
import { COMPACT_VERB, compactionHealth } from './compact.mjs';
import { DERIVABLE_CLASSES, isDerivedEvent } from './derive.mjs';
import { SURFACE, fillRowText, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import { CLASS, openablePath } from './inventory.mjs';
import { MARKER_REFUSAL, readMarker } from './marker.mjs';
import { QUERY_VERB } from './query.mjs';
import { REBUILD_VERB } from './rebuild.mjs';
import { materializeRegistry } from './registry.mjs';
import { classifyRootStatus } from './root-status.mjs';
import {
  COMPOSITE,
  FRESHNESS,
  INTEGRITY,
  PRESENCE,
  assertStatusCode,
} from './status.mjs';
import { VERIFY_VERB } from './verify.mjs';

/** The frozen version. Changing what doctor checks, or what it refuses to do, means v2. */
export const DOCTOR_VERSION = 'doctor-v1';

/** The verb's name, as an operator types it. Spelled once; every surface reads it. */
export const DOCTOR_VERB = 'doctor';

/** The report this verb hands its caller. */
export const DOCTOR_REPORT_SCHEMA = 'doctor-report-v1';

/** The failure table this verb speaks from. */
export const DOCTOR_SURFACE = SURFACE.DOCTOR;

/**
 * What doctor writes: nothing. As data rather than as a sentence, so the claim is countable.
 *
 * @type {ReadonlyArray<string>}
 */
export const WRITES = Object.freeze([]);

/** The sentence that rides on every report, so the bound is never merely implied. */
export const REPORTING_ONLY =
  'doctor reports and never repairs: it wrote nothing, quarantined nothing, re-materialized '
  + 'nothing and broke no lock. Every line names the verb that would act.';

// -- the subsystems ------------------------------------------------------------

/** The seven subsystems, in the order the plan names them and the order they are checked. */
export const SUBSYSTEM = Object.freeze({
  REGISTRY_INDEX: 'registry-index',
  ACK_LATENCY: 'ack-latency',
  STALENESS: 'staleness',
  CAP_PROXIMITY: 'cap-proximity',
  EXPORT_RECENCY: 'export-recency',
  LOCK_LIVENESS: 'lock-liveness',
  MARKER_IDENTITY: 'marker-identity',
});

/** @type {ReadonlyArray<string>} */
export const SUBSYSTEMS = Object.freeze(Object.values(SUBSYSTEM));

/** The heading an operator reads, per subsystem. */
export const SUBSYSTEM_TITLE = Object.freeze({
  [SUBSYSTEM.REGISTRY_INDEX]: 'registry / index consistency',
  [SUBSYSTEM.ACK_LATENCY]: 'ack latency (durability)',
  [SUBSYSTEM.STALENESS]: 'staleness (roots and rows)',
  [SUBSYSTEM.CAP_PROXIMITY]: 'cap proximity',
  [SUBSYSTEM.EXPORT_RECENCY]: 'export-bundle recency',
  [SUBSYSTEM.LOCK_LIVENESS]: 'lock-file liveness',
  [SUBSYSTEM.MARKER_IDENTITY]: 'marker / identity presence',
});

/** The verb each subsystem points at when it has something to report. Doctor runs none. */
export const SUBSYSTEM_REMEDY_VERB = Object.freeze({
  [SUBSYSTEM.REGISTRY_INDEX]: REBUILD_VERB,
  [SUBSYSTEM.ACK_LATENCY]: EXPORT_VERB,
  [SUBSYSTEM.STALENESS]: VERIFY_VERB,
  [SUBSYSTEM.CAP_PROXIMITY]: COMPACT_VERB,
  [SUBSYSTEM.EXPORT_RECENCY]: EXPORT_VERB,
  [SUBSYSTEM.LOCK_LIVENESS]: QUERY_VERB,
  [SUBSYSTEM.MARKER_IDENTITY]: VERIFY_VERB,
});

// -- the rows ------------------------------------------------------------------

/** The class-varying doctor row stems. */
export const DOCTOR_CLASS_STEM = Object.freeze({
  NO_ROWS: 'DOCTOR_NO_ROWS',
  UNKNOWN: 'DOCTOR_UNKNOWN',
  STALE: 'DOCTOR_STALE',
});

/** The doctor rows that do not vary by class. */
export const DOCTOR_CODE = Object.freeze({
  INDEX_ABSENT: 'DOCTOR_INDEX_ABSENT',
  INDEX_UNREACHABLE: 'DOCTOR_INDEX_UNREACHABLE',
  INDEX_UNREADABLE: 'DOCTOR_INDEX_UNREADABLE',
  INDEX_UNPARSEABLE: 'DOCTOR_INDEX_UNPARSEABLE',
  INDEX_MOJIBAKE: 'DOCTOR_INDEX_MOJIBAKE',
  LOG_TORN: 'DOCTOR_LOG_TORN',
  SNAPSHOT_DIVERGED: 'DOCTOR_SNAPSHOT_DIVERGED',
  IDENTITY_CONFLICT: 'DOCTOR_IDENTITY_CONFLICT',
  MARKER_ABSENT: 'DOCTOR_MARKER_ABSENT',
  MARKER_UNPARSEABLE: 'DOCTOR_MARKER_UNPARSEABLE',
  ROOT_ABSENT: 'DOCTOR_ROOT_ABSENT',
  ROOT_UNREACHABLE: 'DOCTOR_ROOT_UNREACHABLE',
  ACK_LATENCY_DEGRADED: 'DOCTOR_ACK_LATENCY_DEGRADED',
  EXPORT_NEVER: 'DOCTOR_EXPORT_NEVER',
  EXPORT_STALE: 'DOCTOR_EXPORT_STALE',
  CAP_WARNING: 'DOCTOR_CAP_WARNING',
  LOCK_TIMEOUT: 'DOCTOR_LOCK_TIMEOUT',
  LOCK_ORPHANED: 'DOCTOR_LOCK_ORPHANED',
  NOTHING_REGISTERED: 'DOCTOR_NOTHING_REGISTERED',
  UNANSWERED: 'DOCTOR_UNANSWERED',
  SKIPPED_REPARSE: 'DOCTOR_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'DOCTOR_PATH_TOO_LONG',
  CASE_COLLISION: 'DOCTOR_CASE_COLLISION',
});

/**
 * The clean code. Not a failure-table row, for the same reason QUERY_OK and VERIFY_OK are
 * not: the tables describe failure STATES of a working surface, and "this subsystem has
 * nothing to report" is the surface working.
 */
export const DOCTOR_OK = 'DOCTOR_OK';

/** @type {Readonly<Record<string, {status: string, text: string}>>} */
export const DOCTOR_LOCAL_ROWS = Object.freeze({
  [DOCTOR_OK]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'doctor OK'),
    text: '{subsystem}: nothing to report ({detail}).',
  }),
});

/** The code suffix each tracked class carries, matching the failure table's own builder. */
const CLASS_SUFFIX = Object.freeze({
  [CLASS.RECEIPT]: 'RECEIPT',
  [CLASS.INSTRUMENT]: 'INSTRUMENT',
  [CLASS.ROADMAP_EVENT]: 'ROADMAP_EVENT',
});

/** The class-varying row code for a stem. @param {string} stem @param {string} className */
export function doctorClassCode(stem, className) {
  const suffix = CLASS_SUFFIX[className];
  if (suffix === undefined) {
    throw new Error(`${DOCTOR_VERB}: ${JSON.stringify(className)} is not a tracked content class`);
  }
  return `${stem}_${suffix}`;
}

/**
 * An outcome for a doctor row: read from the frozen table, or from the local clean row.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {{ok?: boolean}} [extra]
 * @returns {Readonly<object>}
 */
export function doctorOutcome(code, params = {}, extra = {}) {
  const local = DOCTOR_LOCAL_ROWS[code];
  if (local !== undefined) {
    return Object.freeze({
      ok: extra.ok !== false,
      code,
      surface: DOCTOR_SURFACE,
      verb: DOCTOR_VERB,
      status: local.status,
      text: fillRowText(local.text, params),
      detail: Object.freeze({ ...params }),
    });
  }
  return Object.freeze({ ...rowOutcome(code, params, extra), verb: DOCTOR_VERB });
}

/** @returns {ReadonlyArray<string>} every frozen doctor row code, for a test that enumerates */
export function doctorRowCodes() {
  return Object.freeze(
    [...rowsForSurface(DOCTOR_SURFACE).map((r) => r.code), DOCTOR_OK].sort(),
  );
}

/** How an index-read failure is spoken on the doctor surface. */
export const READ_CODE_ROW = Object.freeze({
  [INDEX_READ_CODE.HOME_ABSENT]: DOCTOR_CODE.INDEX_ABSENT,
  [INDEX_READ_CODE.HOME_UNREACHABLE]: DOCTOR_CODE.INDEX_UNREACHABLE,
  [INDEX_READ_CODE.SNAPSHOT_UNREADABLE]: DOCTOR_CODE.INDEX_UNREADABLE,
  [INDEX_READ_CODE.SNAPSHOT_UNPARSEABLE]: DOCTOR_CODE.INDEX_UNPARSEABLE,
  [INDEX_READ_CODE.SNAPSHOT_MOJIBAKE]: DOCTOR_CODE.INDEX_MOJIBAKE,
  [INDEX_READ_CODE.LOG_TORN_TAIL]: DOCTOR_CODE.LOG_TORN,
  [INDEX_READ_CODE.LOCK_TIMEOUT]: DOCTOR_CODE.LOCK_TIMEOUT,
  [INDEX_READ_CODE.UNKNOWN]: DOCTOR_CODE.UNANSWERED,
});

/** @param {string} code @returns {string|null} */
export function doctorCodeForReadCode(code) {
  return READ_CODE_ROW[code] ?? null;
}

/** The hazard axis, as doctor speaks it. */
export const HAZARD_ROW = Object.freeze({
  SKIPPED_REPARSE: DOCTOR_CODE.SKIPPED_REPARSE,
  PATH_TOO_LONG: DOCTOR_CODE.PATH_TOO_LONG,
  CASE_COLLISION: DOCTOR_CODE.CASE_COLLISION,
});

// -- the worst-condition ladder ------------------------------------------------

/**
 * The rank of every status doctor can report, worst last.
 *
 * WHY UNKNOWN IS THE TOP RUNG. A subsystem that could not be checked hides whatever it would
 * have said, so it is worse than a subsystem that was checked and found something: the second
 * is a fact the operator can act on, the first is an unbounded number of unknown facts. An
 * order that put DEGRADED above UNKNOWN would let a portfolio nobody could read exit quieter
 * than one that reported a real problem.
 */
export const STATUS_RANK = Object.freeze({
  [INTEGRITY.OK]: 0,
  [INTEGRITY.EMPTY]: 1,
  [FRESHNESS.FRESH]: 0,
  [FRESHNESS.STALE]: 2,
  [COMPOSITE.DEGRADED]: 3,
  [INTEGRITY.TORN]: 4,
  [INTEGRITY.UNCLASSIFIED]: 4,
  [INTEGRITY.UNPARSEABLE]: 5,
  [INTEGRITY.MOJIBAKE]: 5,
  [INTEGRITY.TAMPERED]: 6,
  [INTEGRITY.IDENTITY_CONFLICT]: 6,
  [PRESENCE.LIVE]: 0,
  [PRESENCE.ABSENT]: 7,
  [PRESENCE.UNREACHABLE]: 8,
  [FRESHNESS.UNKNOWN]: 9,
});

/** The three rungs of the exit ladder. */
export const EXIT_CODE = Object.freeze({
  CLEAN: 0,
  CONDITION_REPORTED: 1,
  UNANSWERED: 2,
});

/** @param {string} status @returns {number} */
export function rankOf(status) {
  const rank = STATUS_RANK[String(status)];
  return rank === undefined ? STATUS_RANK[FRESHNESS.UNKNOWN] : rank;
}

/**
 * The worst of a set of statuses. Empty input is the clean status: a subsystem with no
 * findings HAS been checked, which is a different fact from one that could not be.
 *
 * @param {ReadonlyArray<string>} statuses @returns {string}
 */
export function worstStatus(statuses) {
  let worst = INTEGRITY.OK;
  for (const status of statuses ?? []) {
    if (rankOf(status) > rankOf(worst)) worst = String(status);
  }
  return assertStatusCode(worst, 'doctor worst status');
}

/** @param {string} status @returns {number} the exit code that status earns */
export function exitCodeFor(status) {
  if (status === FRESHNESS.UNKNOWN) return EXIT_CODE.UNANSWERED;
  return rankOf(status) >= STATUS_RANK[FRESHNESS.STALE]
    ? EXIT_CODE.CONDITION_REPORTED
    : EXIT_CODE.CLEAN;
}

// -- one subsystem line --------------------------------------------------------

/**
 * One subsystem's line: its findings, its worst status, and the sentence an operator reads.
 *
 * @param {{id: string, findings?: ReadonlyArray<object>, clean?: string}} parts
 * @returns {Readonly<object>}
 */
export function subsystemLine(parts) {
  const id = String(parts.id);
  const findings = Object.freeze([...(parts.findings ?? [])]);
  const status = worstStatus(findings.map((f) => f.status));
  const clean = doctorOutcome(DOCTOR_OK, {
    subsystem: SUBSYSTEM_TITLE[id] ?? id,
    detail: parts.clean ?? 'checked',
  });
  const spoken = findings.length === 0 ? [clean] : findings;
  return Object.freeze({
    id,
    title: SUBSYSTEM_TITLE[id] ?? id,
    checked: true,
    ok: rankOf(status) <= STATUS_RANK[INTEGRITY.EMPTY],
    status,
    codes: Object.freeze(spoken.map((f) => f.code)),
    findings: Object.freeze(spoken),
    remedy_verb: SUBSYSTEM_REMEDY_VERB[id] ?? null,
    text: `${SUBSYSTEM_TITLE[id] ?? id} [${status}]: ${spoken.map((f) => f.text).join(' ')}`,
  });
}

/**
 * The line a subsystem gets when the pass could not read the index at all.
 *
 * Every subsystem still gets one. A health report that simply omits the checks it could not
 * run reads, at a glance, exactly like a report where those checks passed.
 *
 * @param {string} id @param {string} reason @returns {Readonly<object>}
 */
export function unansweredLine(id, reason) {
  const finding = doctorOutcome(DOCTOR_CODE.UNANSWERED, { reason });
  return Object.freeze({
    id,
    title: SUBSYSTEM_TITLE[id] ?? id,
    checked: false,
    ok: false,
    status: finding.status,
    codes: Object.freeze([finding.code]),
    findings: Object.freeze([finding]),
    remedy_verb: SUBSYSTEM_REMEDY_VERB[id] ?? null,
    text: `${SUBSYSTEM_TITLE[id] ?? id} [${finding.status}]: ${finding.text}`,
  });
}

// -- the checks ----------------------------------------------------------------

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** @param {Readonly<object>} read @returns {object} the snapshot document, or an empty shape */
function snapshotOf(read) {
  const value = read.snapshot_value;
  return isPlainObject(value) ? value : {};
}

/** @param {ReadonlyArray<object>} events @returns {Record<string, number>} rows per class */
function rowsPerClass(events) {
  const counts = {};
  for (const className of DERIVABLE_CLASSES) counts[className] = 0;
  for (const event of events ?? []) {
    if (!isDerivedEvent(event)) continue;
    const className = String(event.class);
    if (counts[className] === undefined) continue;
    counts[className] += 1;
  }
  return counts;
}

/**
 * Registry / index consistency: does the derived snapshot still describe the log that
 * produced it, and does membership resolve without a conflict?
 *
 * @param {{read: object, view: object, events: ReadonlyArray<object>}} input
 * @returns {Readonly<object>}
 */
export function checkRegistryIndex(input) {
  const { read, view, events } = input;
  const findings = [];
  const snapshot = snapshotOf(read);
  const freshness = isPlainObject(snapshot.freshness) ? snapshot.freshness : {};
  const body = isPlainObject(snapshot.body) ? snapshot.body : {};
  const logHead = Number(read.head_seq ?? 0);
  const snapshotHead = Number(freshness.head_seq ?? 0);

  for (const conflict of view.conflicts ?? []) {
    const paths = conflict.paths ?? [];
    findings.push(doctorOutcome(DOCTOR_CODE.IDENTITY_CONFLICT, {
      project_id: conflict.project_id ?? '(unrecorded id)',
      path: paths[0] ?? '(unrecorded path)',
      other_path: paths[1] ?? '(unrecorded path)',
    }));
  }

  for (const ignored of view.ignored ?? []) {
    if (ignored.status !== INTEGRITY.UNPARSEABLE) continue;
    findings.push(doctorOutcome(DOCTOR_CODE.INDEX_UNPARSEABLE, {
      reason: `log seq ${ignored.seq} is a ${ignored.type} event this engine cannot use`,
    }));
  }

  // A snapshot computed from a head the log no longer reaches is the stale-restore shape: the
  // log moved BACKWARDS relative to the artifact derived from it, which cannot happen to an
  // append-only file by itself. The other direction - a snapshot behind the log - is the
  // ordinary D-3 tail and belongs to cap proximity, not here.
  if (read.snapshot_present === true && snapshotHead > logHead) {
    findings.push(doctorOutcome(DOCTOR_CODE.SNAPSHOT_DIVERGED, {
      snapshot_seq: snapshotHead,
      log_seq: logHead,
    }));
  }

  // Rows in the derived artifact naming a project membership no longer resolves.
  const known = new Set((view.projects ?? []).map((p) => p.project_id));
  const strays = new Set();
  for (const project of Array.isArray(body.projects) ? body.projects : []) {
    const id = project?.project_id;
    if (typeof id === 'string' && id !== '' && !known.has(id)) strays.add(id);
  }
  for (const id of [...strays].sort()) {
    findings.push(doctorOutcome(DOCTOR_CODE.SNAPSHOT_DIVERGED, {
      snapshot_seq: snapshotHead,
      log_seq: logHead,
      project_id: id,
    }));
  }

  if ((view.projects ?? []).length === 0) {
    findings.push(doctorOutcome(DOCTOR_CODE.NOTHING_REGISTERED, {}, { ok: true }));
  }

  const perClass = rowsPerClass(events);
  for (const className of DERIVABLE_CLASSES) {
    if (perClass[className] > 0) continue;
    findings.push(doctorOutcome(
      doctorClassCode(DOCTOR_CLASS_STEM.NO_ROWS, className),
      { count: 0 },
      { ok: true },
    ));
  }

  // The index home's own NG-2 hazards, re-spoken on this surface. They arrive as index-read
  // outcomes carrying a path-hazard STATUS, and the status is what they are keyed on: a
  // hazard that reached this line as an integrity code would be the laundering status.mjs
  // refuses in code, and re-keying on the code string would break the moment a row is renamed.
  for (const hazard of read.hazards ?? []) {
    const code = HAZARD_ROW[String(hazard.status ?? '')];
    if (code === undefined) continue;
    const detail = isPlainObject(hazard.detail) ? hazard.detail : {};
    findings.push(doctorOutcome(code, {
      path: detail.path ?? '(unrecorded path)',
      target: detail.target ?? '(no target)',
      other_path: detail.other_path ?? '(unrecorded path)',
    }));
  }

  return subsystemLine({
    id: SUBSYSTEM.REGISTRY_INDEX,
    findings,
    clean:
      `${(view.projects ?? []).length} project(s) resolve, snapshot head ${snapshotHead} of `
      + `log head ${logHead}`,
  });
}

/**
 * Ack latency: how long the engine has been asking Anchor to honour a commit-intent.
 *
 * @param {{events: ReadonlyArray<object>, now: number, threshold_days?: number}} input
 * @returns {Readonly<object>}
 */
export function checkAckLatency(input) {
  const health = durabilityHealth({
    events: input.events,
    now: input.now,
    threshold_days: input.threshold_days,
  });
  const findings = [];
  if (health.degraded === true) {
    findings.push(doctorOutcome(DOCTOR_CODE.ACK_LATENCY_DEGRADED, {
      receipts_at_risk: health.receipts_at_risk,
      days_degraded: health.days_degraded,
    }));
  }
  const line = subsystemLine({
    id: SUBSYSTEM.ACK_LATENCY,
    findings,
    clean:
      `${health.acknowledged?.length ?? 0} intent(s) acknowledged, `
      + `${health.unacknowledged?.length ?? 0} awaiting an ack under the `
      + `${health.threshold_days ?? ACK_THRESHOLD_DAYS}-day threshold`,
  });
  return Object.freeze({ ...line, health });
}

/**
 * Staleness: which roots are live, and which rows the index no longer vouches for.
 *
 * Doctor does NOT re-hash anything here - that is `steward verify`, and running it from a
 * health pass would make reading the report an act that changes the report. What doctor reads
 * is the freshness block the last verify or rebuild wrote, plus the presence of each root
 * right now, which is cheap and changes nothing.
 *
 * @param {{read: object, view: object, events: ReadonlyArray<object>, fsx?: object}} input
 * @returns {Readonly<object>}
 */
export function checkStaleness(input) {
  const { read, view, events } = input;
  const findings = [];
  const snapshot = snapshotOf(read);
  const freshness = isPlainObject(snapshot.freshness) ? snapshot.freshness : {};
  const perProject = isPlainObject(freshness.per_project) ? freshness.per_project : {};
  const rows = (events ?? []).filter(isDerivedEvent);
  let live = 0;

  for (const project of view.projects ?? []) {
    const id = project.project_id;
    const probed = classifyRootStatus(project.current_path, { fsx: input.fsx });
    const owned = rows.filter((row) => row.project_id === id);
    const countFor = (className) => owned.filter((row) => row.class === className).length;

    if (probed.presence === PRESENCE.LIVE) {
      live += 1;
      const recorded = isPlainObject(perProject[id]) ? perProject[id] : {};
      if (recorded.freshness === FRESHNESS.STALE) {
        for (const className of DERIVABLE_CLASSES) {
          const count = countFor(className);
          if (count === 0) continue;
          findings.push(doctorOutcome(
            doctorClassCode(DOCTOR_CLASS_STEM.STALE, className),
            { count, project_id: id },
          ));
        }
      }
      continue;
    }

    findings.push(doctorOutcome(
      probed.presence === PRESENCE.ABSENT
        ? DOCTOR_CODE.ROOT_ABSENT
        : DOCTOR_CODE.ROOT_UNREACHABLE,
      { project_id: id, path: project.current_path, errno: probed.errno ?? probed.reason ?? '' },
    ));

    // The rows of a root nobody could read are RETAINED and reported UNKNOWN. They are never
    // dropped from the count: a portfolio that shrinks when a disk is unplugged is the exact
    // silence the loud-unknown criterion forbids.
    for (const className of DERIVABLE_CLASSES) {
      const count = countFor(className);
      if (count === 0) continue;
      findings.push(doctorOutcome(
        doctorClassCode(DOCTOR_CLASS_STEM.UNKNOWN, className),
        { count, project_id: id, path: project.current_path },
      ));
    }
  }

  return subsystemLine({
    id: SUBSYSTEM.STALENESS,
    findings,
    clean: `${live} of ${(view.projects ?? []).length} root(s) live, ${rows.length} row(s) retained`,
  });
}

/**
 * Cap proximity: every numeric bound this system declares, measured rather than assumed.
 *
 * @param {{read: object, events: ReadonlyArray<object>, home?: string, paths?: object,
 *          env?: object}} input
 * @returns {Readonly<object>}
 */
export function checkCapProximity(input) {
  const { read, events } = input;
  const findings = [];
  const snapshot = snapshotOf(read);
  const freshness = isPlainObject(snapshot.freshness) ? snapshot.freshness : {};
  const logHead = Number(read.head_seq ?? 0);
  const snapshotHead = Number(freshness.head_seq ?? 0);
  const tail = Math.max(0, logHead - snapshotHead);

  const measured = [
    capStatusFor('events_before_compaction', (events ?? []).length),
    capStatusFor('tail_events', tail),
  ];
  for (const cap of measured) {
    if (cap.level === CAP_LEVEL.WITHIN) continue;
    findings.push(doctorOutcome(DOCTOR_CODE.CAP_WARNING, {
      cap: cap.cap,
      observed: cap.observed,
      value: cap.value,
      threshold: cap.threshold,
      on_exceeded: cap.on_exceeded,
    }));
  }

  // W18 computes the compaction subsystem's own line; doctor reads it rather than recomputing
  // the ceiling, so the warning cannot fire at two slightly different moments.
  const compaction = compactionHealth({
    events,
    home: input.home,
    paths: input.paths,
    env: input.env,
  });
  for (const entry of compaction.at_cap ?? []) {
    findings.push(doctorOutcome(DOCTOR_CODE.CAP_WARNING, {
      cap: 'superseded_entries',
      observed: entry.superseded ?? CAPS.superseded_entries,
      value: CAPS.superseded_entries,
      threshold: CAPS.superseded_entries,
      on_exceeded: `${COMPACT_VERB} reports the overflow by name`,
    }));
  }

  const line = subsystemLine({
    id: SUBSYSTEM.CAP_PROXIMITY,
    findings,
    clean: measured.map((cap) => `${cap.cap} ${cap.observed}/${cap.value}`).join(', '),
  });
  return Object.freeze({ ...line, caps: Object.freeze(measured), compaction });
}

/**
 * Export-bundle recency: how long ago a copy last left this box.
 *
 * @param {{events: ReadonlyArray<object>, now: number, health?: object}} input
 * @returns {Readonly<object>}
 */
export function checkExportRecency(input) {
  const health = input.health ?? durabilityHealth({ events: input.events, now: input.now });
  const recency = exportRecency({
    events: input.events,
    now: input.now,
    degraded_since: health.degraded_since ?? null,
  });
  const findings = [];
  if (recency.ever !== true) {
    findings.push(doctorOutcome(DOCTOR_CODE.EXPORT_NEVER, {}));
  } else if (health.degraded === true && recency.covers !== true) {
    findings.push(doctorOutcome(DOCTOR_CODE.EXPORT_STALE, {
      last_export_days: recency.last_export_days,
      days_degraded: health.days_degraded,
    }));
  }
  const line = subsystemLine({
    id: SUBSYSTEM.EXPORT_RECENCY,
    findings,
    clean: recency.text,
  });
  return Object.freeze({ ...line, recency });
}

/**
 * Lock-file liveness: is anybody holding the ONE portfolio lock, and are they alive?
 *
 * Checked AFTER the read has released the lock, which is why this cannot report the pass's
 * own lock as a holder. A lock held by a live writer is not a problem and is reported as
 * such; a lock stamped with a pid that is gone is a killed writer, and doctor names it and
 * breaks nothing - breaking it is the next writer's business, under W5's stale-lock policy.
 *
 * @param {{lock: string, fsx?: object, hostname?: string, kill?: Function}} input
 * @returns {Readonly<object>}
 */
export function checkLockLiveness(input) {
  const fsx = input.fsx ?? fs;
  const findings = [];
  let holder = null;

  let text;
  try {
    text = fsx.readFileSync(openablePath(input.lock), 'utf8');
  } catch (err) {
    const errno = (err && err.code) || '';
    if (errno !== 'ENOENT') {
      findings.push(doctorOutcome(DOCTOR_CODE.UNANSWERED, {
        reason: `the lock at ${input.lock} could not be read (${errno})`,
      }));
    }
    return Object.freeze({
      ...subsystemLine({
        id: SUBSYSTEM.LOCK_LIVENESS,
        findings,
        clean: 'no writer holds the portfolio lock',
      }),
      holder: null,
    });
  }

  holder = parseLockStamp(text);
  const sameHost = holder !== null && holder.hostname === (input.hostname ?? undefined);
  const alive = holder !== null && Number.isInteger(holder.pid)
    ? isProcessAlive(holder.pid, { kill: input.kill })
    : null;

  if (holder === null) {
    findings.push(doctorOutcome(DOCTOR_CODE.UNANSWERED, {
      reason: `the lock at ${input.lock} carries a holder stamp this engine cannot parse`,
    }));
  } else if (alive === false && (input.hostname === undefined || sameHost)) {
    findings.push(doctorOutcome(DOCTOR_CODE.LOCK_ORPHANED, {
      path: input.lock,
      pid: holder.pid,
      hostname: holder.hostname ?? '(unrecorded host)',
    }));
  }

  return Object.freeze({
    ...subsystemLine({
      id: SUBSYSTEM.LOCK_LIVENESS,
      findings,
      clean: holder === null
        ? 'a lock file is present with no readable holder'
        : `held by pid ${holder.pid} on ${holder.hostname}, which is running`,
    }),
    holder: holder === null ? null : Object.freeze({ ...holder, alive }),
  });
}

/**
 * Marker / identity presence: the git-free byte source recovery reads.
 *
 * @param {{view: object, fsx?: object}} input
 * @returns {Readonly<object>}
 */
export function checkMarkerIdentity(input) {
  const findings = [];
  let present = 0;

  for (const project of input.view.projects ?? []) {
    const probed = classifyRootStatus(project.current_path, { fsx: input.fsx });
    if (probed.presence !== PRESENCE.LIVE) {
      // A marker inside a root nobody can read is not ABSENT - nobody looked. Presence of the
      // ROOT is the staleness subsystem's line; repeating it here as a marker verdict would
      // report one fact twice and, worse, as two different kinds of fact.
      continue;
    }
    const marker = readMarker(project.current_path, { fs: input.fsx });
    if (marker.ok === true) {
      present += 1;
      if (marker.marker.project_id !== project.project_id) {
        findings.push(doctorOutcome(DOCTOR_CODE.IDENTITY_CONFLICT, {
          project_id: project.project_id,
          path: project.current_path,
          other_path: `${marker.path} (claims ${marker.marker.project_id})`,
        }));
      }
      continue;
    }
    findings.push(doctorOutcome(
      marker.code === MARKER_REFUSAL.ABSENT
        ? DOCTOR_CODE.MARKER_ABSENT
        : DOCTOR_CODE.MARKER_UNPARSEABLE,
      {
        project_id: project.project_id,
        path: marker.path,
        reason: marker.problems?.[0]?.text ?? String(marker.code),
      },
    ));
  }

  return subsystemLine({
    id: SUBSYSTEM.MARKER_IDENTITY,
    findings,
    clean: `${present} live root(s) carry a valid marker`,
  });
}

// -- the verb ------------------------------------------------------------------

/**
 * `steward doctor`.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number|Date,
 *          threshold_days?: number, boundMs?: number, staleMs?: number, lockOpts?: object,
 *          hostname?: string, kill?: Function}} [opts]
 * @returns {Readonly<object>} the doctor-report-v1
 */
export function runDoctor(opts = {}) {
  const paths = indexPathsFrom(opts);
  const nowMs = new Date(opts.now ?? Date.now()).getTime();

  // quarantine:false is the reporting-only rule in its sharpest form: a torn tail is REPORTED
  // here and moved by the next verb that writes. A health pass that quarantined bytes would be
  // a health pass that changed the portfolio it was asked to describe.
  const read = openIndexForRead({ ...opts, paths, quarantine: false });

  if (read.ok !== true) {
    const code = doctorCodeForReadCode(read.code) ?? DOCTOR_CODE.INDEX_UNREADABLE;
    const outcome = doctorOutcome(code, {
      home: paths.home,
      root: '<project root>',
      errno: read.detail?.errno ?? '',
      reason: read.text ? read.text : String(read.code),
      offset: read.detail?.offset ?? 0,
      snapshot_seq: 0,
      log_seq: 0,
    });
    const subsystems = SUBSYSTEMS.map((id) => unansweredLine(id, outcome.text));
    return freezeReport({
      paths,
      answered: false,
      subsystems,
      outcome,
      head_seq: 0,
      project_count: 0,
      now: nowMs,
    });
  }

  const events = read.events ?? [];
  const view = materializeRegistry(events);

  const registry = checkRegistryIndex({ read, view, events });
  const ack = checkAckLatency({ events, now: nowMs, threshold_days: opts.threshold_days });
  const staleness = checkStaleness({ read, view, events, fsx: opts.fsx });
  const caps = checkCapProximity({
    read,
    events,
    home: opts.home ?? paths.home,
    paths: opts.paths,
    env: opts.env,
  });
  const exports_ = checkExportRecency({ events, now: nowMs, health: ack.health });
  const lock = checkLockLiveness({
    lock: paths.lock,
    fsx: opts.fsx,
    hostname: opts.hostname,
    kill: opts.kill,
  });
  const markers = checkMarkerIdentity({ view, fsx: opts.fsx });

  const subsystems = [registry, ack, staleness, caps, exports_, lock, markers];

  return freezeReport({
    paths,
    answered: true,
    subsystems,
    outcome: null,
    head_seq: Number(read.head_seq ?? 0),
    project_count: (view.projects ?? []).length,
    now: nowMs,
    view,
  });
}

/**
 * Assemble the frozen report. Separate from runDoctor so both the answered and the unanswered
 * path produce EXACTLY the same shape - a caller must not have to ask which one it got.
 *
 * @param {object} parts @returns {Readonly<object>}
 */
function freezeReport(parts) {
  const subsystems = Object.freeze([...parts.subsystems]);
  const status = worstStatus(subsystems.map((s) => s.status));
  return Object.freeze({
    ok: exitCodeFor(status) === EXIT_CODE.CLEAN,
    schema: DOCTOR_REPORT_SCHEMA,
    version: DOCTOR_VERSION,
    verb: DOCTOR_VERB,
    surface: DOCTOR_SURFACE,
    answered: parts.answered,
    home: parts.paths.home,
    log: parts.paths.log,
    snapshot: parts.paths.snapshot,
    lock: parts.paths.lock,
    status,
    exit_code: exitCodeFor(status),
    subsystems,
    subsystem_count: subsystems.length,
    lines: Object.freeze(subsystems.map((s) => s.text)),
    codes: Object.freeze(subsystems.flatMap((s) => [...s.codes])),
    head_seq: parts.head_seq,
    project_count: parts.project_count,
    outcome: parts.outcome,
    // The reporting-only claim, stated on every run and countable rather than implied.
    wrote: false,
    writes: WRITES,
    reporting_only: REPORTING_ONLY,
    checked_at: new Date(parts.now).toISOString(),
  });
}

// -- rendering and the CLI shape -----------------------------------------------

/**
 * What an operator sees: one line per subsystem, then the verdict.
 *
 * @param {Readonly<object>} report @returns {string}
 */
export function renderDoctor(report) {
  const lines = [
    `steward ${DOCTOR_VERB} - ${report.home}`,
    '',
    ...report.subsystems.map((s) => `  ${s.text}`),
    '',
    `verdict: ${report.status} (exit ${report.exit_code})`,
    report.reporting_only,
  ];
  return lines.join('\n');
}

/** The flags this verb accepts. It has no --fix, and that is the point. */
export const DOCTOR_FLAG = Object.freeze({
  HOME: '--home',
  JSON: '--json',
});

/** @type {ReadonlyArray<string>} */
export const DOCTOR_FLAGS = Object.freeze(Object.values(DOCTOR_FLAG));

/** The refusal for an argument this verb does not have. */
export const DOCTOR_USAGE = 'DOCTOR_USAGE';

/**
 * @param {string[]} [argv]
 * @returns {{ok: boolean, home: string|null, json: boolean, text: string}}
 */
export function parseDoctorArgs(argv = []) {
  let home = null;
  let json = false;
  for (let i = 0; i < argv.length; i += 1) {
    const token = String(argv[i]);
    if (token === DOCTOR_FLAG.JSON) {
      json = true;
      continue;
    }
    if (token === DOCTOR_FLAG.HOME) {
      home = argv[i + 1] === undefined ? null : String(argv[i + 1]);
      i += 1;
      continue;
    }
    return {
      ok: false,
      home,
      json,
      text:
        `steward ${DOCTOR_VERB}: ${token} is not a flag this verb has. `
        + `${doctorUsage()} There is deliberately no repair flag: doctor reports, and the verb `
        + 'that acts is the one named on the line that reported it.',
    };
  }
  return { ok: true, home, json, text: '' };
}

/** @returns {string} */
export function doctorUsage() {
  return `usage: steward ${DOCTOR_VERB} [${DOCTOR_FLAG.HOME} <dir>] [${DOCTOR_FLAG.JSON}]`;
}

/**
 * The CLI entry: parse, run, report. Never throws for an operator condition.
 *
 * @param {string[]} [argv] @param {object} [opts]
 * @returns {Readonly<object>}
 */
export function doctor(argv = [], opts = {}) {
  const args = parseDoctorArgs(argv);
  if (!args.ok) {
    return Object.freeze({
      ok: false,
      schema: DOCTOR_REPORT_SCHEMA,
      version: DOCTOR_VERSION,
      verb: DOCTOR_VERB,
      code: DOCTOR_USAGE,
      status: assertStatusCode(FRESHNESS.UNKNOWN, 'doctor usage'),
      exit_code: EXIT_CODE.UNANSWERED,
      subsystems: Object.freeze([]),
      lines: Object.freeze([args.text]),
      wrote: false,
      writes: WRITES,
      text: args.text,
    });
  }
  const report = runDoctor({ ...opts, home: args.home ?? opts.home });
  return Object.freeze({ ...report, json: args.json, rendered: renderDoctor(report) });
}

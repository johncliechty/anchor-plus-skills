/**
 * W3 - the seven failure tables, as data.
 *
 * WHY THIS FILE EXISTS RATHER THAN JUST THE MARKDOWN. The wave ships two artifacts that
 * must agree forever: planning/steward-tracking-2026-07/stage1/failure-tables.md (what a
 * human reads) and the generated red stubs under test/failure-stubs/ (what the build
 * enforces). If the rows live in the markdown, the generator has to parse prose, and the
 * first time somebody edits a table cell the stubs and the doc drift apart silently -
 * which is precisely the "documented and never armed" failure journal 0080 was written
 * about. So the rows live HERE, once, and both artifacts are renderings of this array.
 * test/w49-failure-stubs.test.mjs asserts all three agree row for row.
 *
 * WHAT A ROW IS. One (surface, failure state, class) triple with:
 *   - a surface refusal code, unique across the whole system;
 *   - the STATUS-v1 code it carries, taken from engine/portfolio/status.mjs (never typed);
 *   - the user-visible text, which is the sentence the operator actually reads;
 *   - the wave that turns the row from red to green.
 *
 * THE DISTINCTIONS THIS TABLE EXISTS TO PRESERVE, each of which is a separate row and not
 * a shade of another row:
 *   - unknown vs empty-but-valid. "I looked and found nothing" and "I could not look" are
 *     different facts and the operator acts differently on each.
 *   - ABSENT vs UNREACHABLE. Deleted project vs unplugged network share.
 *   - UNPARSEABLE vs MOJIBAKE. Bad JSON vs valid JSON carrying encoding damage - the
 *     second parses perfectly and is silently wrong forever if it is not named.
 *   - each NG-2 path hazard on its own row, on the path-hazard axis, never laundered into
 *     UNPARSEABLE (status.mjs refuses that fold in code; this table refuses it in prose).
 *   - every row whose answer differs by class carries a receipt AND an instrument AND a
 *     roadmap-event variant, each with its own code and its own text. No class-varying row
 *     may exist in receipt-only form - that is the class-symmetry claim, counted rather
 *     than described.
 *
 * Placeholders in user-visible text are written {like_this}. They are filled by the
 * implementing wave; the table freezes the sentence, not the values.
 *
 * Stdlib only.
 */

import {
  AXIS,
  COMPOSITE,
  FAILURE_STATE,
  FRESHNESS,
  INTEGRITY,
  PATH_HAZARD,
  PRESENCE,
  REQUIRED_FAILURE_STATES,
  assertStatusCode,
  axisOf,
  isFailureState,
} from './status.mjs';
import { CLASS } from './inventory.mjs';

/**
 * The NINE surfaces, in the order the plan names them.
 *
 * W3 shipped seven and DEFERRED two - compaction and doctor - because neither verb existed
 * yet and a table written against a verb nobody has built is a table nobody can implement.
 * W19 discharges that deferral: the last two entries below are the Phase-1 deferrals coming
 * due, in the same 0080 format, with unknown and empty as separate rows exactly as the other
 * seven have them. Nothing about the format is relaxed for arriving late.
 */
export const SURFACE = Object.freeze({
  INDEX_READ: 'index-read',
  INDEX_WRITE: 'index-write',
  INGEST: 'ingest',
  REBUILD: 'rebuild',
  RECONCILE: 'reconcile',
  VERIFY: 'verify',
  QUERY: 'query',
  COMPACT: 'compact',
  DOCTOR: 'doctor',
});

/**
 * The two tables W3 deferred and W19 discharges. Named as data rather than described in
 * prose so the closure audit can COUNT the discharge instead of trusting a sentence.
 *
 * @type {ReadonlyArray<string>}
 */
export const PHASE_1_DEFERRED_SURFACES = Object.freeze([SURFACE.COMPACT, SURFACE.DOCTOR]);

/** @type {ReadonlyArray<string>} */
export const SURFACES = Object.freeze(Object.values(SURFACE));

/** Human titles for the rendered document. */
export const SURFACE_TITLE = Object.freeze({
  [SURFACE.INDEX_READ]: 'Index read',
  [SURFACE.INDEX_WRITE]: 'Index write',
  [SURFACE.INGEST]: 'Ingest (the DERIVED write path)',
  [SURFACE.REBUILD]: 'Rebuild',
  [SURFACE.RECONCILE]: 'Reconcile',
  [SURFACE.VERIFY]: 'Verify',
  [SURFACE.QUERY]: 'Query',
  [SURFACE.COMPACT]: 'Compaction (the event ceiling)',
  [SURFACE.DOCTOR]: 'Doctor (the health pass)',
});

/**
 * The three tracked classes, with the id suffix and the noun each variant uses. Identity
 * markers are not here: a marker is not a tracked content class, and its failures are
 * reconcile and verify rows rather than a fourth column.
 */
export const CLASS_VARIANTS = Object.freeze([
  Object.freeze({ class: CLASS.RECEIPT, suffix: 'RECEIPT', label: CLASS.RECEIPT }),
  Object.freeze({ class: CLASS.INSTRUMENT, suffix: 'INSTRUMENT', label: CLASS.INSTRUMENT }),
  Object.freeze({ class: CLASS.ROADMAP_EVENT, suffix: 'ROADMAP_EVENT', label: CLASS.ROADMAP_EVENT }),
]);

// -- row builders --------------------------------------------------------------

/**
 * @param {string} surface @param {string} code @param {string} state @param {string} status
 * @param {string} wave @param {string} text
 * @returns {Readonly<object>}
 */
function row(surface, code, state, status, wave, text) {
  assertStatusCode(status, `failure row ${code}`);
  if (!isFailureState(state)) throw new Error(`failure row ${code}: ${state} is not a 0080 state`);
  return Object.freeze({
    id: code,
    code,
    surface,
    state,
    status,
    axis: axisOf(status),
    class: null,
    wave,
    text,
    // Filled in by the wave that implements the row; W3 ships every row unimplemented,
    // which is what makes the generated stub RED rather than absent.
    implemented_by: null,
  });
}

/**
 * The class-symmetry builder. One call produces THREE rows - receipt, instrument and
 * roadmap-event - so a class-varying row cannot be written in receipt-only form even by
 * accident. That is legs 3-12 of the class-symmetry matrix expressed as an API.
 *
 * @param {string} surface @param {string} stem @param {string} state @param {string} status
 * @param {string} wave @param {(label: string) => string} textFor
 * @returns {Array<Readonly<object>>}
 */
function classRows(surface, stem, state, status, wave, textFor) {
  return CLASS_VARIANTS.map((v) =>
    Object.freeze({
      ...row(surface, `${stem}_${v.suffix}`, state, status, wave, textFor(v.label)),
      class: v.class,
    }),
  );
}

const S = FAILURE_STATE;

// -- table 1: index read -------------------------------------------------------

const INDEX_READ_ROWS = [
  row(SURFACE.INDEX_READ, 'INDEX_READ_HOME_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W5',
    'index home not found at {home}; nothing has been registered yet - run steward register {root}, or set STEWARD_HOME if the index lives elsewhere.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_HOME_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W5',
    'index home at {home} could not be reached ({errno}); this is not the same as absent - the index may exist and be temporarily unreadable, so nothing was rebuilt and nothing was discarded.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W5',
    'the portfolio lock was held by pid {pid} for longer than the starvation bound of {bound_s}s; the read was refused rather than taken unlocked, and no index state changed.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_SNAPSHOT_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W5',
    'the snapshot at {path} is not parseable JSON ({reason} at byte {offset}); the log is intact - run steward rebuild to regenerate the snapshot from it.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_SNAPSHOT_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W5',
    'the snapshot at {path} parses but carries UTF-8-read-as-CP1252 damage at byte {offset}; it is refused rather than ingested, because a hash taken over damaged bytes would preserve the damage forever.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_LOG_TORN_TAIL', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W5',
    "the log's final line is truncated mid-write; it was moved to {log}.torn-{seq} and counted in a recovery receipt - no bytes were discarded and every event before it is intact."),
  row(SURFACE.INDEX_READ, 'INDEX_READ_SNAPSHOT_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the snapshot head hash does not match the log head it claims to derive from; it is refused as authoritative and the log is read instead.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_SNAPSHOT_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W5',
    'the snapshot at {path} exists but its bytes could not be read ({errno}); the index is reported unreachable rather than empty, so nothing counts this as a portfolio of zero projects.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W5',
    'the index is valid and contains zero rows; this is EMPTY, not UNKNOWN - the steward looked and there is genuinely nothing recorded yet.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W5',
    'the index could not be read to a known state ({reason}); its contents are UNKNOWN, which is not the same as empty - no count is reported rather than reporting zero.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W5',
    'an entry under the index home ({path}) is a reparse point aimed at {target}; it is recorded and not followed, so a junction under the index home cannot redirect a read outside it.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W5',
    'the index path {path} exceeds MAX_PATH; it is opened through the extended-length prefix or reported on this row, and is never reported as a missing index.'),
  row(SURFACE.INDEX_READ, 'INDEX_READ_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W5',
    'two entries under the index home differ only by case ({path} and {other_path}); both are named, because which one a case-insensitive filesystem serves is not stable.'),
];

// -- table 2: index write ------------------------------------------------------

const INDEX_WRITE_ROWS = [
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_HOME_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W5',
    'index home {home} does not exist and could not be created; the append was refused and the caller was NOT told the event was durable.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_HOME_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W5',
    'index home {home} could not be reached ({errno}); the append was refused, reported distinctly from the absent case because the index may still exist.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W5',
    'the portfolio lock was not acquired within the starvation bound of {bound_s}s (holder pid {pid}); the writer failed with this status rather than writing unlocked or waiting forever.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_TORN_APPEND', S.DEPENDENCY_SLOW_OR_KILLED, INTEGRITY.TORN, 'W5',
    'the process was killed between writeSync and fsync; the partial final line is quarantined to {log}.torn-{seq} on next open and counted, never silently dropped.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_RENAME_BLOCKED', S.DEPENDENCY_SLOW_OR_KILLED, PRESENCE.UNREACHABLE, 'W5',
    'the snapshot rename over {path} was blocked ({errno}) past the bounded retry; the previous snapshot is intact and the temp file was left for the sweep, never read as authoritative.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_SEQ_CONFLICT', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W5',
    'the log head moved between seq allocation and append, so the allocated sequence is no longer head_seq+1; the append was refused rather than duplicating a sequence number.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_LOG_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W5',
    'the log could not be read to its head because line {line} is unparseable; appending would build on an unknown head, so it was refused.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_DENIED', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W5',
    'the index home is not writable ({errno}); the event was not appended and success was not reported - the source-of-truth write, if any, still stands.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_EMPTY_BATCH', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W5',
    'the flush had zero events to append; this is a valid no-op reported as EMPTY, and it neither advances head_seq nor rewrites the snapshot.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_MOJIBAKE_REFUSED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W5',
    'the event to be appended carries UTF-8-read-as-CP1252 damage in {field}; the append is refused rather than folding the damage into the log, where every later hash would faithfully preserve it.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W5',
    'durability of the append could not be determined ({reason}); it is reported UNKNOWN rather than success, and the divergence sweep settles it on next start.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W5',
    'the log or snapshot path {path} is a reparse point aimed at {target}; the write is refused rather than followed, so an append can never be redirected outside the index home.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W5',
    'the temp file path {path} exceeds MAX_PATH; it is opened through the extended-length prefix or the write is refused on this row, and the name is never truncated to fit.'),
  row(SURFACE.INDEX_WRITE, 'INDEX_WRITE_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W5',
    'a temp or sidecar name collides by case with an existing entry ({path} and {other_path}); both are named and the write is refused rather than overwriting the wrong file.'),
];

// -- table 3: ingest -----------------------------------------------------------

const INGEST_ROWS = [
  ...classRows(SURFACE.INGEST, 'INGEST_SOURCE_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W9',
    (c) => `the ${c} file {path} vanished between the source-of-truth write and the derive step; no row was invented for it and the project reads STALE.`),
  ...classRows(SURFACE.INGEST, 'INGEST_SOURCE_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W9',
    (c) => `the ${c} file {path} is not parseable ({reason}); it is recorded as an UNPARSEABLE row carrying its path, never silently skipped.`),
  ...classRows(SURFACE.INGEST, 'INGEST_SOURCE_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W9',
    (c) => `the ${c} file {path} carries UTF-8-read-as-CP1252 damage at byte {offset}; it is recorded as MOJIBAKE, which is deliberately not the same row as UNPARSEABLE.`),
  ...classRows(SURFACE.INGEST, 'INGEST_SOURCE_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W9',
    (c) => `the ${c} file {path} is valid and contains zero entries; it is recorded EMPTY, not UNKNOWN - the file was read and it really is empty.`),
  ...classRows(SURFACE.INGEST, 'INGEST_FRESHNESS_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W9',
    (c) => `the ${c} row could not be confirmed durable in the index; its freshness is UNKNOWN - neither FRESH nor EMPTY - until the divergence sweep settles it.`),
  row(SURFACE.INGEST, 'INGEST_APPEND_FAILED', S.BACKING_STORE_UNREADABLE, FRESHNESS.STALE, 'W9',
    'the file was written but the index did not record it ({reason}); the source-of-truth write stands, the project reads STALE, and the next startup sweep regenerates the row.'),
  row(SURFACE.INGEST, 'INGEST_ROOT_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W9',
    'the project root {path} could not be reached ({errno}) during ingest; this is reported distinctly from an absent root and no identity binding changed.'),
  row(SURFACE.INGEST, 'INGEST_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W9',
    'the portfolio lock was not acquired within the starvation bound after the project lock released; the derived event stays buffered and the verb reports this status rather than hanging.'),
  row(SURFACE.INGEST, 'INGEST_UNCLASSIFIED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNCLASSIFIED, 'W9',
    '{path} matched no inventory-v1 discovery path; it is recorded UNCLASSIFIED with its path and counted in the totality equation - never silently ingested and never silently ignored.'),
  row(SURFACE.INGEST, 'INGEST_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W9',
    '{path} is a symlink, junction or other reparse point; it was recorded with its target {target} and NOT followed, and it is not laundered into UNPARSEABLE.'),
  row(SURFACE.INGEST, 'INGEST_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W9',
    '{path} exceeds MAX_PATH and could not be opened even through the extended-length prefix; it is named on its own row rather than merged with a parse failure.'),
  row(SURFACE.INGEST, 'INGEST_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W9',
    '{path} and {other_path} differ only by case under one root; BOTH paths are recorded on their own row, because either could be the one that ingests.'),
];

// -- table 4: rebuild ----------------------------------------------------------

const REBUILD_ROWS = [
  ...classRows(SURFACE.REBUILD, 'REBUILD_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W10',
    (c) => `the ${c} file {path} is not parseable ({reason}); it becomes an UNPARSEABLE row carrying reason and path, so parsed + unparseable + unclassified == discovered still holds.`),
  ...classRows(SURFACE.REBUILD, 'REBUILD_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W10',
    (c) => `the ${c} file {path} carries mojibake at byte {offset}; it is recorded MOJIBAKE rather than UNPARSEABLE, so the damage is nameable instead of generic.`),
  ...classRows(SURFACE.REBUILD, 'REBUILD_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W10',
    (c) => `no ${c} files were discovered under any live root; the class reports EMPTY, which is not the same as a class whose roots could not be read.`),
  ...classRows(SURFACE.REBUILD, 'REBUILD_RETAINED_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W11',
    (c) => `${c} rows for a non-live root were replayed from the log; their freshness is UNKNOWN and the rows are RETAINED - absence never reduces the retained set.`),
  row(SURFACE.REBUILD, 'REBUILD_ROOT_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W11',
    'registered root {path} is gone (ENOENT with its parent readable); an explicit unknown row is emitted with its last-known path and project_id, and no row is dropped.'),
  row(SURFACE.REBUILD, 'REBUILD_ROOT_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W11',
    'registered root {path} could not be read ({errno}); it is UNREACHABLE, rendered distinctly from ABSENT, and no identity binding is changed.'),
  row(SURFACE.REBUILD, 'REBUILD_LOG_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W17',
    'the live log is missing, so rebuild has no NATIVE input; this is recovery rather than rebuild - run steward recover-log, which reports the LOST window honestly.'),
  row(SURFACE.REBUILD, 'REBUILD_WALK_BOUND_EXCEEDED', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W10',
    'the walk of {path} reached its bound of {cap} entries; that root is reported UNKNOWN rather than returning a short list as if it were complete.'),
  row(SURFACE.REBUILD, 'REBUILD_LOG_TORN', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W10',
    "the log's final line is torn; it is quarantined and counted before replay, so the rebuild proceeds from a known head rather than an ambiguous one."),
  row(SURFACE.REBUILD, 'REBUILD_PATH_ESCAPE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W10',
    "recorded path {path} resolves outside its project's registered root; the row is refused as TAMPERED, rendered loudly, and its content is never ingested."),
  row(SURFACE.REBUILD, 'REBUILD_IDENTITY_CONFLICT', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.IDENTITY_CONFLICT, 'W10',
    'project_id {project_id} was found live at {path} and {other_path}; both paths are reported, neither is bound, the project is counted exactly once, and no new id is minted.'),
  row(SURFACE.REBUILD, 'REBUILD_UNCLASSIFIED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNCLASSIFIED, 'W10',
    '{path} matched no inventory-v1 discovery path; it becomes an UNCLASSIFIED row with its path so the totality equation still balances.'),
  row(SURFACE.REBUILD, 'REBUILD_INDEX_UNWRITABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W10',
    'the rebuilt snapshot could not be written to the index home ({errno}); the previous snapshot is left intact and no partial bytes are served.'),
  row(SURFACE.REBUILD, 'REBUILD_NO_PROJECTS', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W10',
    'no projects are registered; the rebuild succeeds and produces a valid EMPTY index, which is a different fact from an index that could not be read.'),
  row(SURFACE.REBUILD, 'REBUILD_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W10',
    '{path} is a reparse point; it was recorded with its target {target} and not followed, so a junction cycle cannot make the rebuild nondeterministic.'),
  row(SURFACE.REBUILD, 'REBUILD_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W10',
    '{path} exceeds MAX_PATH; it is opened through the extended-length prefix or recorded on this row, and never dropped from the walk.'),
  row(SURFACE.REBUILD, 'REBUILD_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W10',
    '{path} and {other_path} differ only by case under one root; both are recorded, because which one a case-insensitive filesystem serves is not stable.'),
];

// -- table 5: reconcile --------------------------------------------------------

const RECONCILE_ROWS = [
  row(SURFACE.RECONCILE, 'RECONCILE_TARGET_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W12',
    'the new path {path} does not exist; no binding was changed and the project still resolves to its last-known path.'),
  row(SURFACE.RECONCILE, 'RECONCILE_TARGET_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W12',
    'the new path {path} could not be read ({errno}); reconcile refuses rather than rebinding on evidence it could not see.'),
  row(SURFACE.RECONCILE, 'RECONCILE_MARKER_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W12',
    'no .steward/project.json marker was found at {path}; reconcile will not rebind a root that carries no claim of identity.'),
  row(SURFACE.RECONCILE, 'RECONCILE_SCAN_BOUND_EXCEEDED', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W12',
    'the bounded scan of {path} reached its limit of {cap} entries; candidates found so far are PROPOSED and the result is marked incomplete rather than presented as exhaustive.'),
  row(SURFACE.RECONCILE, 'RECONCILE_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W12',
    'the portfolio lock was not acquired within the starvation bound; no reconcile event was appended and no binding changed.'),
  row(SURFACE.RECONCILE, 'RECONCILE_MARKER_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W12',
    'the marker at {path} is not parseable ({reason}); it is refused rather than defaulted, because a defaulted identity is a forged one.'),
  row(SURFACE.RECONCILE, 'RECONCILE_MARKER_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W12',
    'the marker at {path} carries mojibake at byte {offset}; it is refused on its own row, distinct from an unparseable marker.'),
  row(SURFACE.RECONCILE, 'RECONCILE_TWO_PLACES', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.IDENTITY_CONFLICT, 'W12',
    'project_id {project_id} is claimed by markers at {path} and {other_path}; every implicit route is refused - only steward reconcile --claim {project_id} {path} resolves it, recording both paths and the loser marker hash.'),
  row(SURFACE.RECONCILE, 'RECONCILE_MARKER_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W12',
    'the marker at {path} claims a project_id the registry never minted, or a registered_path outside the registry; the claim is refused and reported loudly.'),
  row(SURFACE.RECONCILE, 'RECONCILE_REGISTRY_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W12',
    'the registry view could not be materialized because the index home is unreadable ({errno}); reconcile refuses rather than rebinding against an unknown registry.'),
  row(SURFACE.RECONCILE, 'RECONCILE_SCAN_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W12',
    'the scan completed and found zero candidate markers; this is EMPTY - the search really did run - and is not the same as a scan that could not be completed.'),
  row(SURFACE.RECONCILE, 'RECONCILE_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W12',
    'the binding could not be decided from the available evidence ({reason}); it is left UNKNOWN and unchanged rather than guessed.'),
  row(SURFACE.RECONCILE, 'RECONCILE_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W12',
    '{path} is a reparse point; the scan recorded it with its target {target} and did not follow it, so a junction cycle cannot hang a scan.'),
  row(SURFACE.RECONCILE, 'RECONCILE_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W12',
    '{path} exceeds MAX_PATH; it is named on its own row, so a marker that cannot be opened is a reported candidate rather than an omission.'),
  row(SURFACE.RECONCILE, 'RECONCILE_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W12',
    '{path} and {other_path} differ only by case; both are reported as separate candidates and neither is bound automatically.'),
];

// -- table 6: verify -----------------------------------------------------------

const VERIFY_ROWS = [
  ...classRows(SURFACE.VERIFY, 'VERIFY_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    (c) => `the ${c} file {path} was hand-edited out of band; its hash no longer matches the recorded row, the project is reported TAMPERED, and its query rows read STALE.`),
  ...classRows(SURFACE.VERIFY, 'VERIFY_TRUNCATED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W14',
    (c) => `the ${c} file {path} is truncated; this is reported on its own row, distinct from a hand-edit and from a stale restore.`),
  ...classRows(SURFACE.VERIFY, 'VERIFY_STALE_RESTORE_SOURCE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    (c) => `the ${c} file {path} holds bytes that hash to a SUPERSEDED version in its own lineage (seq {found_seq}, current {current_seq}); it was restored from an older copy, which is neither a hand-edit nor a truncation.`),
  ...classRows(SURFACE.VERIFY, 'VERIFY_SOURCE_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W14',
    (c) => `the ${c} file {path} is gone while its row survives; the row is retained and the file is reported ABSENT, never quietly deleted from the portfolio.`),
  ...classRows(SURFACE.VERIFY, 'VERIFY_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W14',
    (c) => `the ${c} store at {path} is valid and holds zero entries; it renders EMPTY with its own text and is never conflated with UNKNOWN.`),
  ...classRows(SURFACE.VERIFY, 'VERIFY_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W14',
    (c) => `the ${c} store could not be re-hashed because its root is not live; its integrity is UNKNOWN, which is neither a pass nor an empty store.`),
  row(SURFACE.VERIFY, 'VERIFY_ROOT_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W14',
    'root {path} could not be read ({errno}); its projects are reported UNREACHABLE and their rows read UNKNOWN rather than being marked verified.'),
  row(SURFACE.VERIFY, 'VERIFY_BOUND_EXCEEDED', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W14',
    'verify reached its bound of {cap} files, or was killed, before completing; the partial result is reported as incomplete and never as a clean bill of health.'),
  row(SURFACE.VERIFY, 'VERIFY_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W14',
    'the portfolio lock was not acquired within the starvation bound; verify reports this status instead of reading the index unlocked.'),
  row(SURFACE.VERIFY, 'VERIFY_STALE_RESTORE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the snapshot was restored from an older copy while the log moved ahead (snapshot head {snapshot_seq}, log head {log_seq}); this is its own named status, distinct from hand-edit and truncation.'),
  row(SURFACE.VERIFY, 'VERIFY_MARKER_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the in-root marker at {path} was edited out of band; identity is reported TAMPERED and no rebinding happens on the strength of an edited claim.'),
  row(SURFACE.VERIFY, 'VERIFY_MARKER_TRUNCATED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W14',
    'the in-root marker at {path} is cut short ({observed_len} of {recorded_len} bytes); truncation is its own row, because a marker half-written and a marker rewritten are different accidents.'),
  row(SURFACE.VERIFY, 'VERIFY_MARKER_STALE_RESTORE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the in-root marker at {path} hashes to a marker this log recorded EARLIER (seq {found_seq}) rather than to the current one (seq {current_seq}); it was restored from an older copy.'),
  row(SURFACE.VERIFY, 'VERIFY_SNAPSHOT_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the snapshot at {path} was edited out of band ({reason}); it is WHOLLY DERIVED, so it is reported TAMPERED and `steward rebuild` is the repair - its content is never trusted over the log.'),
  row(SURFACE.VERIFY, 'VERIFY_SNAPSHOT_TRUNCATED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W14',
    'the snapshot at {path} is cut short at {observed_len} bytes and does not close; truncation is its own row, distinct from a hand-edit and from a stale restore.'),
  row(SURFACE.VERIFY, 'VERIFY_LOG_TORN', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W14',
    "the log's final line is torn; verify reports it, quarantines it and counts it in a recovery receipt rather than treating the log as clean."),
  row(SURFACE.VERIFY, 'VERIFY_LOG_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'a log line was edited out of band ({reason} at seq {seq}); the log is the ONE never-deletable store, so an edited line is reported TAMPERED and never silently replayed as fact.'),
  row(SURFACE.VERIFY, 'VERIFY_LOG_STALE_RESTORE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W14',
    'the log head is at seq {log_seq}, BEHIND the head {snapshot_seq} the snapshot was computed from; the log was restored from an older copy and events after {log_seq} are gone.'),
  row(SURFACE.VERIFY, 'VERIFY_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W14',
    'the file at {path} could not be parsed at all ({reason}); it is reported UNPARSEABLE, which is a different fact from a file that parses cleanly and fails its hash.'),
  row(SURFACE.VERIFY, 'VERIFY_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W14',
    'a verified file carries UTF-8-read-as-CP1252 damage at byte {offset}; MOJIBAKE is reported on its own row so it is never rendered as a generic parse failure.'),
  row(SURFACE.VERIFY, 'VERIFY_INDEX_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W14',
    'the index could not be read ({errno}), so there is no baseline to verify against; verify refuses rather than reporting every project as fine.'),
  row(SURFACE.VERIFY, 'VERIFY_NOTHING_REGISTERED', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W14',
    'no projects are registered, so there is nothing to verify; this renders EMPTY, distinct from an index that could not be read.'),
  row(SURFACE.VERIFY, 'VERIFY_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W14',
    '{path} is a reparse point; verify records it with its target {target} and does not follow it, so a junction cannot make one root appear to verify twice.'),
  row(SURFACE.VERIFY, 'VERIFY_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W14',
    '{path} exceeds MAX_PATH; it is reported on its own row rather than counted among the files that verified cleanly.'),
  row(SURFACE.VERIFY, 'VERIFY_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W14',
    '{path} and {other_path} differ only by case; both are reported, because verifying one and reporting both as clean would be a lie.'),
];

// -- table 7: query ------------------------------------------------------------

const QUERY_ROWS = [
  ...classRows(SURFACE.QUERY, 'QUERY_EMPTY', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W13',
    (c) => `no ${c} rows match; the result is EMPTY and explicitly complete - the index was read and there genuinely are none.`),
  ...classRows(SURFACE.QUERY, 'QUERY_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W13',
    (c) => `${c} rows from a non-live root are returned with freshness UNKNOWN; the contribution is present and marked, never omitted.`),
  row(SURFACE.QUERY, 'QUERY_INDEX_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W13',
    'no index exists at {home}; the query reports ABSENT rather than returning zero results, because zero results and no index are different facts.'),
  row(SURFACE.QUERY, 'QUERY_INDEX_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W13',
    'the index home could not be reached ({errno}); the query refuses rather than answering from nothing.'),
  row(SURFACE.QUERY, 'QUERY_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W13',
    'the portfolio lock was not acquired within the starvation bound while merging the log tail; the query reports this status rather than serving snapshot-only results as complete.'),
  row(SURFACE.QUERY, 'QUERY_CURSOR_STALE', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.STALE, 'W13',
    'a rebuild ran between paged calls, so this cursor no longer addresses the rows it was issued against; re-run the query from the first page rather than skipping rows silently.'),
  row(SURFACE.QUERY, 'QUERY_SNAPSHOT_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W13',
    'the snapshot is not parseable ({reason}); the query refuses and points at steward rebuild instead of answering from a partial parse.'),
  row(SURFACE.QUERY, 'QUERY_PROJ_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W13',
    'a proj projection field carries mojibake; the row is returned with the damage NAMED, so a --contains match is never silently wrong.'),
  row(SURFACE.QUERY, 'QUERY_TAIL_TORN', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W13',
    "the log tail's final line is torn; it is quarantined and the answer states that the tail was truncated, rather than merging a partial event."),
  row(SURFACE.QUERY, 'QUERY_ROW_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W13',
    'a matched row resolves to a path outside its registered root; it is rendered as TAMPERED and its content is not served as a result.'),
  row(SURFACE.QUERY, 'QUERY_IDENTITY_CONFLICT', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.IDENTITY_CONFLICT, 'W13',
    'project_id {project_id} is live at {path} and {other_path}; results name both paths, count the project once, and bind neither.'),
  row(SURFACE.QUERY, 'QUERY_UNCLASSIFIED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNCLASSIFIED, 'W13',
    'a matched row is UNCLASSIFIED - discovered, but matching no inventory-v1 class; it is returned with its path rather than dropped from the answer.'),
  row(SURFACE.QUERY, 'QUERY_INDEX_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W13',
    'the index bytes could not be read ({errno}); the query reports the store unreadable and returns no rows, rather than returning zero rows as a complete answer.'),
  row(SURFACE.QUERY, 'QUERY_NO_MATCHES', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W13',
    'the predicate matched no rows in a healthy, populated index; the answer is EMPTY and explicitly complete.'),
  row(SURFACE.QUERY, 'QUERY_ROOT_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W13',
    "a contributing root's freshness could not be determined; its rows are returned marked UNKNOWN, so omission can never pass as unknown."),
  row(SURFACE.QUERY, 'QUERY_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W13',
    "a returned row's source path was recorded SKIPPED_REPARSE at discovery; the hazard travels with the row instead of being dropped from the answer."),
  row(SURFACE.QUERY, 'QUERY_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W13',
    "a returned row's source path was recorded PATH_TOO_LONG at discovery; the row is rendered with its hazard rather than omitted."),
  row(SURFACE.QUERY, 'QUERY_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W13',
    "a returned row's source path was recorded CASE_COLLISION at discovery; both colliding paths are named on the result."),
];

// -- table 8: compaction (W3 deferred it; W19 discharges it) --------------------

/**
 * The COMPACTION surface, in 0080 format.
 *
 * WHY THESE CODES ARE NOT compact.mjs's CODES. engine/portfolio/compact.mjs owns the VERB's
 * outcome rows - COMPACT_OK, COMPACT_NOT_DUE, COMPACT_SUPERSEDED_OVERFLOW and the retirement
 * refusals - which are the dispositions of a compaction that RAN. These rows are the
 * different question 0080 asks: what does this surface say when the thing underneath it is
 * missing, slow, garbage, unreadable, or valid-and-empty. The two sets are disjoint by
 * construction and the W19 closure audit asserts that disjointness, so neither can quietly
 * become a second wording of the other.
 */
const COMPACT_ROWS_TABLE = [
  row(SURFACE.COMPACT, 'COMPACT_HOME_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W19',
    'there is no index home at {home} to compact; compaction shortens a log it can find, and reports its absence rather than creating one.'),
  row(SURFACE.COMPACT, 'COMPACT_HOME_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W19',
    'the index home at {home} could not be reached ({errno}); no head was staged and no segment retired, because a compaction from a partial read carries forward a smaller portfolio than the one on disk.'),
  row(SURFACE.COMPACT, 'COMPACT_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W19',
    'the portfolio lock was not acquired within the starvation bound; compaction refuses rather than rewriting the log while another writer is appending to it.'),
  row(SURFACE.COMPACT, 'COMPACT_STAGING_TORN', S.DEPENDENCY_SLOW_OR_KILLED, INTEGRITY.TORN, 'W19',
    'the compacted head was cut short at {written} of {total} line(s) - the process was killed or the device filled; the staging file is removed and the live log is untouched and still authoritative.'),
  row(SURFACE.COMPACT, 'COMPACT_EVENT_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W19',
    'log line {seq} does not parse ({reason}); it is carried forward verbatim and named here, because an engine that dropped the bytes it cannot classify would compact away the evidence.'),
  row(SURFACE.COMPACT, 'COMPACT_EVENT_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W19',
    'log line {seq} carries UTF-8-read-as-CP1252 damage at byte {offset}; it parses perfectly, so it is named on its own row rather than folded into a checkpoint as if it were clean.'),
  row(SURFACE.COMPACT, 'COMPACT_HEAD_TAMPERED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W19',
    'the compacted head at {log} no longer hashes to what this compaction wrote ({reason}); the retired segment is kept and retirement is refused, because the head is the only thing that could replace it.'),
  row(SURFACE.COMPACT, 'COMPACT_EVENT_UNCLASSIFIED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNCLASSIFIED, 'W19',
    'log line {seq} matches no event type this engine knows; it is carried into the compacted head untouched and counted here, never folded and never dropped.'),
  row(SURFACE.COMPACT, 'COMPACT_IDENTITY_CONFLICT', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.IDENTITY_CONFLICT, 'W19',
    'project_id {project_id} appears at {path} and {other_path} in the events being folded; both paths are carried into the checkpoint rows, the project is counted once, and neither path is bound.'),
  ...classRows(SURFACE.COMPACT, 'COMPACT_FOLD_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W19',
    (c) => `a ${c} checkpoint row this compaction built does not validate ({reason}); nothing is written, because an invalid checkpoint in an append-only log cannot be edited out afterwards.`),
  row(SURFACE.COMPACT, 'COMPACT_SEGMENT_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W19',
    'the retired segment at {retired} could not be read ({errno}); it holds the only copy of the bodies the head replaced, so it is neither deleted nor assumed intact.'),
  row(SURFACE.COMPACT, 'COMPACT_NO_EVENTS', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W19',
    'the log at {log} is valid and holds zero events, so there is nothing to fold; this is EMPTY - what a portfolio that has not written yet looks like - and never a compaction of nothing.'),
  ...classRows(SURFACE.COMPACT, 'COMPACT_NO_ROWS', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W19',
    (c) => `no ${c} rows exist to fold into checkpoints; the class is reported EMPTY with its own text, so a class that was never written is never confused with a class whose rows were folded away.`),
  row(SURFACE.COMPACT, 'COMPACT_LINEAGE_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W19',
    'the lineage for {path} in project {project_id} cannot be counted from the compacted head alone - an earlier segment has already been deleted; the list is a floor rather than a total and says so.'),
  ...classRows(SURFACE.COMPACT, 'COMPACT_LINEAGE_FLOOR', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W19',
    (c) => `the ${c} lineage on {path} sits at the caps.superseded_entries bound of {cap}; {omitted} older entries (seq {from_seq} through {to_seq}) are reported rather than dropped in silence, and the list is now a floor, not a total.`),
  row(SURFACE.COMPACT, 'COMPACT_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W19',
    '{path} was recorded SKIPPED_REPARSE with target {target} when its row was written; the hazard travels into the checkpoint row rather than being lost at the fold.'),
  row(SURFACE.COMPACT, 'COMPACT_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W19',
    '{path} exceeds MAX_PATH; the retired segment and the staged head are opened through the extended-length prefix or the run is refused on this row, never half-written.'),
  row(SURFACE.COMPACT, 'COMPACT_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W19',
    '{path} and {other_path} differ only by case, so they are two rows a fold could merge into one; both are kept as separate checkpoint rows and both are named here.'),
];

// -- table 9: doctor (W3 deferred it; W19 discharges it) ------------------------

/**
 * The DOCTOR surface, in 0080 format.
 *
 * Doctor REPORTS and never repairs, so every row below is a sentence rather than an action.
 * That is the point: the one place an operator reads every detector must be the one place
 * that cannot quietly change what it is describing.
 */
const DOCTOR_ROWS = [
  row(SURFACE.DOCTOR, 'DOCTOR_INDEX_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W19',
    'there is no index at {home}; every subsystem below is reported unchecked rather than healthy, because nothing has been registered here yet - run steward register {root} first.'),
  row(SURFACE.DOCTOR, 'DOCTOR_INDEX_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W19',
    'the index home {home} could not be reached ({errno}); doctor reports what it could not check rather than reporting a portfolio it never read as fine.'),
  row(SURFACE.DOCTOR, 'DOCTOR_ROOT_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W19',
    'project {project_id} is registered at {path}, which is not there; its rows are retained, its identity is unchanged, and it renders as the unknown row rather than shrinking the portfolio.'),
  row(SURFACE.DOCTOR, 'DOCTOR_ROOT_UNREACHABLE', S.DEPENDENCY_MISSING, PRESENCE.UNREACHABLE, 'W19',
    'project {project_id} at {path} could not be reached ({errno}) - a network share, a denied ACL or a cloud placeholder; this is reported distinctly from a root that is not there at all.'),
  row(SURFACE.DOCTOR, 'DOCTOR_MARKER_ABSENT', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W19',
    'the in-root marker for project {project_id} is not at {path}; the registry still binds the project, and the marker is what makes recovery possible without this index - restore it before you need it.'),
  row(SURFACE.DOCTOR, 'DOCTOR_EXPORT_NEVER', S.DEPENDENCY_MISSING, PRESENCE.ABSENT, 'W19',
    'last export-bundle: never. Local disk is the only copy of everything this portfolio has ever recorded; steward export-bundle is the verb that changes that.'),
  row(SURFACE.DOCTOR, 'DOCTOR_LOCK_TIMEOUT', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.UNKNOWN, 'W19',
    'the portfolio lock was not acquired within the starvation bound, so the health pass read nothing; doctor reports UNKNOWN rather than reading the index unlocked.'),
  row(SURFACE.DOCTOR, 'DOCTOR_LOCK_ORPHANED', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.STALE, 'W19',
    'the lock at {path} is held by pid {pid} on {hostname}, which is not running - a writer was killed mid-act. The next writer breaks it by the stale-lock policy; doctor names it and breaks nothing.'),
  row(SURFACE.DOCTOR, 'DOCTOR_ACK_LATENCY_DEGRADED', S.DEPENDENCY_SLOW_OR_KILLED, COMPOSITE.DEGRADED, 'W19',
    'durability is DEGRADED: {receipts_at_risk} commit-intent(s) have gone {days_degraded} day(s) without an acknowledgement, so state written here is not yet committed anywhere else.'),
  row(SURFACE.DOCTOR, 'DOCTOR_EXPORT_STALE', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.STALE, 'W19',
    'last export-bundle: {last_export_days} days ago, which is older than the degradation that started {days_degraded} day(s) ago - the only off-box copy predates the problem it would be used to recover from.'),
  row(SURFACE.DOCTOR, 'DOCTOR_CAP_WARNING', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.STALE, 'W19',
    '{cap} is at {observed} of {value} (the warning fires at {threshold}); at the ceiling the disposition is {on_exceeded}, and it is stated here while there is still time to act on it.'),
  row(SURFACE.DOCTOR, 'DOCTOR_INDEX_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W19',
    'the index could not be parsed ({reason}); doctor names the store and the reason and stops there - repairing it is steward rebuild, which is a verb the operator runs, not one a health pass runs for them.'),
  row(SURFACE.DOCTOR, 'DOCTOR_INDEX_MOJIBAKE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.MOJIBAKE, 'W19',
    'the index carries UTF-8-read-as-CP1252 damage at byte {offset}; it parses cleanly, which is exactly why it gets its own line rather than being reported as a parse failure or not at all.'),
  row(SURFACE.DOCTOR, 'DOCTOR_LOG_TORN', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TORN, 'W19',
    "the log's final line is torn ({reason}); doctor reports it and quarantines nothing - the quarantine and its recovery receipt belong to the next verb that writes."),
  row(SURFACE.DOCTOR, 'DOCTOR_SNAPSHOT_DIVERGED', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.TAMPERED, 'W19',
    'the snapshot was computed from head {snapshot_seq} while the log stands at {log_seq}, or its bytes no longer match what the log derives; the snapshot is wholly derived, so the log is believed and steward rebuild is the repair.'),
  row(SURFACE.DOCTOR, 'DOCTOR_IDENTITY_CONFLICT', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.IDENTITY_CONFLICT, 'W19',
    'project_id {project_id} is claimed at {path} and {other_path}; both are named, the project is counted once, neither is bound, and only steward reconcile --claim resolves it.'),
  row(SURFACE.DOCTOR, 'DOCTOR_MARKER_UNPARSEABLE', S.DEPENDENCY_RETURNS_GARBAGE, INTEGRITY.UNPARSEABLE, 'W19',
    'the marker at {path} does not validate ({reason}); identity is still bound by the log, and the marker - the git-free byte source recovery reads - cannot be trusted until it is rewritten.'),
  row(SURFACE.DOCTOR, 'DOCTOR_INDEX_UNREADABLE', S.BACKING_STORE_UNREADABLE, PRESENCE.UNREACHABLE, 'W19',
    'the index bytes could not be read ({errno}); every subsystem is reported unanswered, because a health pass that renders a portfolio it never opened as healthy is the exact silence this verb exists to break.'),
  row(SURFACE.DOCTOR, 'DOCTOR_NOTHING_REGISTERED', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W19',
    'the index opened cleanly and holds zero projects; this is EMPTY - the pass really did run - and it is never rendered as UNKNOWN.'),
  ...classRows(SURFACE.DOCTOR, 'DOCTOR_NO_ROWS', S.EMPTY_BUT_VALID, INTEGRITY.EMPTY, 'W19',
    (c) => `the portfolio holds zero ${c} rows; the class is reported EMPTY on its own line so a class nobody has written yet is never mistaken for a class whose rows went unread.`),
  row(SURFACE.DOCTOR, 'DOCTOR_UNANSWERED', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W19',
    'this subsystem could not be checked ({reason}); UNKNOWN is reported rather than a pass, because "we could not look" and "there is nothing wrong" are the two facts a health surface must never merge.'),
  ...classRows(SURFACE.DOCTOR, 'DOCTOR_UNKNOWN', S.UNKNOWN, FRESHNESS.UNKNOWN, 'W19',
    (c) => `${c} rows on non-live roots carry freshness UNKNOWN; they are counted and reported here, so a class whose root vanished is loud rather than absent from the count.`),
  ...classRows(SURFACE.DOCTOR, 'DOCTOR_STALE', S.DEPENDENCY_SLOW_OR_KILLED, FRESHNESS.STALE, 'W19',
    (c) => `{count} ${c} row(s) read STALE against project {project_id}; steward verify is the verb that re-hashes them, and doctor reports the drift without touching a byte.`),
  row(SURFACE.DOCTOR, 'DOCTOR_SKIPPED_REPARSE', S.PATH_HAZARD, PATH_HAZARD.SKIPPED_REPARSE, 'W19',
    '{path} in the index home is a reparse point pointing at {target}; it is reported and not followed, so a junction inside the index home cannot make the health pass wander.'),
  row(SURFACE.DOCTOR, 'DOCTOR_PATH_TOO_LONG', S.PATH_HAZARD, PATH_HAZARD.PATH_TOO_LONG, 'W19',
    '{path} exceeds MAX_PATH; it is opened through the extended-length prefix or reported on this row, never counted among the files that read cleanly.'),
  row(SURFACE.DOCTOR, 'DOCTOR_CASE_COLLISION', S.PATH_HAZARD, PATH_HAZARD.CASE_COLLISION, 'W19',
    '{path} and {other_path} in the index home differ only by case; both are named, because which one a case-insensitive filesystem serves is not stable across machines.'),
];

// -- the frozen table ----------------------------------------------------------

/** @type {ReadonlyArray<Readonly<object>>} every failure row, in surface order. */
export const FAILURE_ROWS = Object.freeze([
  ...INDEX_READ_ROWS,
  ...INDEX_WRITE_ROWS,
  ...INGEST_ROWS,
  ...REBUILD_ROWS,
  ...RECONCILE_ROWS,
  ...VERIFY_ROWS,
  ...QUERY_ROWS,
  ...COMPACT_ROWS_TABLE,
  ...DOCTOR_ROWS,
]);

/** @param {string} surface @returns {Array<Readonly<object>>} */
export function rowsForSurface(surface) {
  return FAILURE_ROWS.filter((r) => r.surface === surface);
}

/** @param {string} code @returns {Readonly<object>|null} */
export function rowForCode(code) {
  return FAILURE_ROWS.find((r) => r.code === code) ?? null;
}

/** @returns {string[]} every row code, in table order */
export function allRowCodes() {
  return FAILURE_ROWS.map((r) => r.code);
}

/** The stub tests generated from this table live here, one file per surface. */
export const STUB_DIR = 'test/failure-stubs';

/** @param {string} surface @returns {string} the stub file name for a surface */
export function stubFileNameFor(surface) {
  return `w5x-${surface}-failures.test.mjs`;
}

// -- rendering one row for an operator -----------------------------------------

/**
 * Fill a row's {placeholders}.
 *
 * An unfilled placeholder is LEFT IN PLACE rather than blanked. A sentence with a visible
 * {errno} tells the reader something was not reported; a sentence with a silent gap reads
 * as if it had been, which is the same class of quiet lie the tables exist to prevent.
 *
 * @param {string} text @param {Record<string, unknown>} [params] @returns {string}
 */
export function fillRowText(text, params = {}) {
  return String(text).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * The outcome object an implementing surface returns for a frozen row.
 *
 * It lives HERE, next to the rows, so that every surface that reports a failure reads the
 * status and the sentence out of the table rather than composing its own - which is the
 * whole reason the rows are code. `ok` exists because a few rows (an empty batch, an
 * extended-length path, a completed quarantine) are NAMED STATES OF A SUCCESSFUL
 * OPERATION, and forcing them to look like failures would teach callers to ignore them.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {{ok?: boolean}} [extra]
 * @returns {Readonly<object>}
 */
export function rowOutcome(code, params = {}, extra = {}) {
  const r = rowForCode(code);
  if (r === null) throw new Error(`failure-tables: ${code} is not a frozen failure row`);
  return Object.freeze({
    ok: extra.ok === true,
    code,
    surface: r.surface,
    state: r.state,
    status: r.status,
    axis: r.axis,
    class: r.class,
    text: fillRowText(r.text, params),
    detail: Object.freeze({ ...params }),
  });
}

// -- self-audit ----------------------------------------------------------------

/**
 * Every structural promise the wave makes about these tables, checked mechanically.
 *
 * This is not decoration. "All seven tables ship in 0080 format with unknown and empty as
 * separate rows and each NG-2 path hazard as its own row, and no class-varying row exists
 * in receipt-only form" is a countable claim, and a claim nothing counts is exactly the
 * prose-property defect journal 0080 named.
 *
 * @returns {{ok: boolean, problems: string[], counts: object}}
 */
export function failureTableIntegrity() {
  const problems = [];
  const seen = new Set();

  for (const r of FAILURE_ROWS) {
    if (seen.has(r.code)) problems.push(`duplicate row code: ${r.code}`);
    seen.add(r.code);
    if (!SURFACES.includes(r.surface)) problems.push(`${r.code}: unknown surface ${r.surface}`);
    if (!isFailureState(r.state)) problems.push(`${r.code}: ${r.state} is not a 0080 failure state`);
    if (axisOf(r.status) === null) problems.push(`${r.code}: ${r.status} is not a STATUS-v1 code`);
    if (!r.text || r.text.length < 40) problems.push(`${r.code}: user-visible text is too thin to be honest`);
    if (r.state === FAILURE_STATE.PATH_HAZARD && r.axis !== AXIS.PATH_HAZARD) {
      problems.push(`${r.code}: a path-hazard row carries ${r.status} from the ${r.axis} axis - that is the laundering NG-2 forbids`);
    }
    if (r.state === FAILURE_STATE.EMPTY_BUT_VALID && r.status !== INTEGRITY.EMPTY) {
      problems.push(`${r.code}: an empty-but-valid row must carry ${INTEGRITY.EMPTY}, not ${r.status}`);
    }
    if (r.state === FAILURE_STATE.UNKNOWN && r.status !== FRESHNESS.UNKNOWN) {
      problems.push(`${r.code}: an unknown row must carry ${FRESHNESS.UNKNOWN}, not ${r.status}`);
    }
  }

  const counts = {};
  for (const surface of SURFACES) {
    const rows = rowsForSurface(surface);
    counts[surface] = rows.length;
    if (!rows.length) {
      problems.push(`${surface}: no rows at all`);
      continue;
    }

    // The five journal-0080 states, each answered.
    for (const required of REQUIRED_FAILURE_STATES) {
      if (!rows.some((r) => r.state === required)) {
        problems.push(`${surface}: no row answers the 0080 state ${required}`);
      }
    }

    // unknown and empty, never collapsed.
    const empties = rows.filter((r) => r.state === FAILURE_STATE.EMPTY_BUT_VALID);
    const unknowns = rows.filter((r) => r.state === FAILURE_STATE.UNKNOWN);
    if (!empties.length) problems.push(`${surface}: no empty-but-valid row`);
    if (!unknowns.length) problems.push(`${surface}: no unknown row - unknown was collapsed into empty`);
    for (const e of empties) {
      if (unknowns.some((u) => u.code === e.code)) problems.push(`${surface}: ${e.code} serves both empty and unknown`);
    }

    // ABSENT and UNREACHABLE, distinct.
    if (!rows.some((r) => r.status === PRESENCE.ABSENT)) problems.push(`${surface}: no ${PRESENCE.ABSENT} row`);
    if (!rows.some((r) => r.status === PRESENCE.UNREACHABLE)) problems.push(`${surface}: no ${PRESENCE.UNREACHABLE} row`);

    // UNPARSEABLE and MOJIBAKE, distinct.
    if (!rows.some((r) => r.status === INTEGRITY.UNPARSEABLE)) problems.push(`${surface}: no ${INTEGRITY.UNPARSEABLE} row`);
    if (!rows.some((r) => r.status === INTEGRITY.MOJIBAKE)) problems.push(`${surface}: no ${INTEGRITY.MOJIBAKE} row`);

    // Each NG-2 path hazard on its own row.
    for (const hazard of Object.values(PATH_HAZARD)) {
      const hits = rows.filter((r) => r.status === hazard);
      if (hits.length !== 1) problems.push(`${surface}: expected exactly one ${hazard} row, found ${hits.length}`);
    }

    // No class-varying row in receipt-only form: a stem present for one class is present
    // for all three, with its own code and its own text.
    const stems = new Map();
    for (const r of rows.filter((x) => x.class !== null)) {
      const suffix = CLASS_VARIANTS.find((v) => v.class === r.class)?.suffix ?? '';
      const stem = r.code.slice(0, r.code.length - suffix.length - 1);
      if (!stems.has(stem)) stems.set(stem, new Map());
      stems.get(stem).set(r.class, r);
    }
    for (const [stem, byClass] of stems) {
      for (const v of CLASS_VARIANTS) {
        if (!byClass.has(v.class)) {
          problems.push(`${surface}: ${stem} has no ${v.class} variant - a class-varying row in receipt-only form`);
        }
      }
      const texts = new Set([...byClass.values()].map((r) => r.text));
      if (texts.size !== byClass.size) {
        problems.push(`${surface}: ${stem} variants share user-visible text, so the class is not really named`);
      }
    }
  }

  return { ok: problems.length === 0, problems, counts };
}

// -- rendering -----------------------------------------------------------------

/** @param {string} s @returns {string} a markdown table cell that cannot break the table */
function cell(s) {
  return String(s).split('|').join('\\|');
}

/** @param {Readonly<object>} r @returns {string} */
function renderRow(r) {
  return `| ${cell(r.code)} | ${cell(r.state)} | ${cell(r.status)} | ${cell(r.axis)} | ${cell(r.class ?? '-')} | ${cell(r.wave)} | ${cell(r.text)} |`;
}

/** @param {string} surface @returns {string[]} */
function renderSurface(surface) {
  const rows = rowsForSurface(surface);
  return [
    `### ${SURFACE_TITLE[surface]} (\`${surface}\`) - ${rows.length} rows`,
    '',
    '| status code | 0080 state | STATUS-v1 | axis | class | wave | user-visible text |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...rows.map(renderRow),
    '',
  ];
}

/**
 * Render the whole document. planning/steward-tracking-2026-07/stage1/failure-tables.md is
 * this output with a prose preamble; the test asserts the doc carries every row.
 *
 * @returns {string}
 */
export function renderFailureTablesMarkdown() {
  const audit = failureTableIntegrity();
  const lines = [];
  for (const surface of SURFACES) lines.push(...renderSurface(surface));
  lines.push(`Total rows: ${FAILURE_ROWS.length}. Structural audit: ${audit.ok ? 'PASS' : audit.problems.join('; ')}.`);
  return lines.join('\n');
}

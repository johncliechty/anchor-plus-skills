/**
 * W4 - the numeric caps, each with its BASIS named.
 *
 * WHY THE BASIS IS A FIELD AND NOT A COMMENT. census.md (W2) measured the real portfolio
 * and found zero items at every inventory-v1 discovery path - not "a few", zero - because
 * nothing has been written through the write authorities yet. It then said, in the section
 * "What W4 may and may not cite", that whatever basis this file chooses must be stated
 * BY NAME here, "because a cap whose basis is unstated is a refusal path nobody can
 * predict". So every entry below carries `basis` and `confirmed_by`, and the two are not
 * the same thing:
 *
 *   - rows_per_query and events_before_compaction were CONFIRMED BY JOHN at the Stage-0
 *     gate (NORTH-STAR.md criterion 6 and the G5 row). Those numbers are settled.
 *   - tail_events and superseded_entries did not exist at that gate - they arrived with
 *     D-3 and D-4 in Stage 2 - so they are PROPOSED here, derived from the census proxy,
 *     and they are labelled PROPOSED rather than dressed up as confirmed. A number nobody
 *     has agreed to should say so in the field an operator can read.
 *   - the proj field/array caps are frozen in the plan's own W9 text (256 characters per
 *     string field, 16 entries per array), so their basis is the plan.
 *   - walk_entries is not re-declared here at all: it is imported from inventory.mjs,
 *     because two copies of one bound is how the two drift.
 *
 * THE 80% RULE, once. Every cap has one warning threshold - 80% of the ceiling - computed
 * by one function. A per-surface warning percentage would be four numbers to keep in step
 * and four chances to render a different one.
 *
 * WHAT HAPPENS AT THE CEILING IS PART OF THE CAP. `on_exceeded` is a closed set, and the
 * query surface's disposition is PAGINATE. That is the mechanical half of the plan's "no
 * refusal on the query surface is reachable by data volume alone": a query that finds more
 * rows than the page cap returns a page and a way to get the next one - it does not refuse.
 * QUERY_REFUSAL_TRIGGER below classifies every query-surface failure row by what actually
 * triggers it, none of them by volume, and test/w55-bqc1-single-source.test.mjs fails if a
 * row is added without a trigger or with the volume one.
 *
 * A tension worth stating rather than hiding: NORTH-STAR criterion 6 (the C6 definition,
 * and the single place BQC-1's behavior is defined) speaks of driving a query past the cap
 * and asserting an explicit refusal, while the Stage-2 plan's W13 done-when requires that
 * no refusal be reachable by data volume alone. This file implements the Stage-2 plan.
 * The residue is recorded as a gate item in
 * planning/steward-tracking-2026-07/stage2/disaster-tree.md; it is the user's call, not
 * this module's.
 *
 * Stdlib only.
 */

import { DEFAULT_WALK_CAP } from './inventory.mjs';
import { SURFACE, rowsForSurface } from './failure-tables.mjs';

/** The frozen cap set's version. */
export const CAPS_VERSION = 'caps-v1';

/** How a cap was arrived at. */
export const BASIS = Object.freeze({
  JOHN_GATE: 'JOHN_CONFIRMED_STAGE0_GATE',
  CENSUS_PROXY: 'CENSUS_PROXY_PROJECTION',
  PLAN_FROZEN: 'PLAN_FROZEN_TEXT',
  MODULE_IMPORT: 'IMPORTED_FROM_INVENTORY_V1',
});

/** Whether a human has agreed to the number, as opposed to where it came from. */
export const CONFIRMATION = Object.freeze({
  CONFIRMED: 'CONFIRMED',
  PROPOSED: 'PROPOSED_PENDING_GATE',
});

/** What happens when a cap is reached. Closed: an unnamed disposition is an unbounded one. */
export const DISPOSITION = Object.freeze({
  PAGINATE: 'PAGINATE',
  RE_MATERIALIZE: 'RE_MATERIALIZE',
  WARN_THEN_COMPACT: 'WARN_THEN_COMPACT',
  TRUNCATE_AND_FLAG: 'TRUNCATE_AND_FLAG',
  REPORT_OVERFLOW: 'REPORT_OVERFLOW',
  REFUSE: 'REFUSE',
});

/** The fraction of a ceiling at which the operator is warned. One number, one rule. */
export const WARN_FRACTION = 0.8;

/**
 * The caps themselves.
 *
 * `cited_from` names the document a reviewer can check the number against. `rationale` is
 * the arithmetic, not an adjective - the census proxy is ~11.2 journal entries per day for
 * one project, which projects to roughly 8,000 items/year for a two-project portfolio and
 * roughly 40,000 for a ten-project one.
 */
export const CAP_ENTRIES = Object.freeze([
  Object.freeze({
    id: 'rows_per_query',
    value: 10000,
    unit: 'rows per query page',
    surface: SURFACE.QUERY,
    on_exceeded: DISPOSITION.PAGINATE,
    basis: BASIS.JOHN_GATE,
    confirmed_by: CONFIRMATION.CONFIRMED,
    cited_from: 'stage0/NORTH-STAR.md criterion 6 and its G5 row',
    rationale:
      'A ten-project portfolio projects to roughly 40,000 items a year at the census proxy ' +
      'rate, so a 10,000-row page is a real page rather than a theoretical one, and the ' +
      'answer past it is another page.',
  }),
  Object.freeze({
    id: 'events_before_compaction',
    value: 50000,
    unit: 'log events',
    surface: null,
    on_exceeded: DISPOSITION.WARN_THEN_COMPACT,
    basis: BASIS.JOHN_GATE,
    confirmed_by: CONFIRMATION.CONFIRMED,
    cited_from: 'stage0/NORTH-STAR.md criterion 6 and its G5 row',
    rationale:
      'census.md put the ten-project projection at the same order of magnitude as this ' +
      'ceiling, which is why it is the number to argue with rather than around: roughly a ' +
      'year of a large portfolio between compactions.',
  }),
  Object.freeze({
    id: 'tail_events',
    value: 2000,
    unit: 'log events after freshness.head_seq',
    surface: SURFACE.QUERY,
    on_exceeded: DISPOSITION.RE_MATERIALIZE,
    basis: BASIS.CENSUS_PROXY,
    confirmed_by: CONFIRMATION.PROPOSED,
    cited_from: 'stage1/census.md proxy row (PROXY_NOT_INVENTORY_V1) via D-3',
    rationale:
      'The D-3 tail is what makes a just-written receipt findable without a snapshot ' +
      'rewrite, so it must be long enough to be normal and short enough to be cheap. At the ' +
      'proxy rate a ten-project portfolio writes ~112 items a day, so 2,000 events is about ' +
      'eighteen days of writing between re-materializations, and a 2,000-line merge is ' +
      'well under a megabyte. Proposed, not confirmed: D-3 did not exist at the Stage-0 gate.',
  }),
  Object.freeze({
    id: 'superseded_entries',
    value: 256,
    unit: 'lineage entries per (project_id, path) checkpoint row',
    surface: null,
    on_exceeded: DISPOSITION.REPORT_OVERFLOW,
    basis: BASIS.CENSUS_PROXY,
    confirmed_by: CONFIRMATION.PROPOSED,
    cited_from: 'stage1/census.md via D-4',
    rationale:
      'D-4 keeps every superseded version of a file as {seq, sha256, byte_len, written_at} ' +
      'so nothing ever written loses its lineage. 256 rewrites of ONE file is far past ' +
      'anything the measured portfolio does; past it the overflow is reported by name and ' +
      'surfaced by doctor, never silently dropped. Proposed, not confirmed: D-4 postdates ' +
      'the Stage-0 gate.',
  }),
  Object.freeze({
    id: 'proj_field_chars',
    value: 256,
    unit: 'characters per proj string field',
    surface: null,
    on_exceeded: DISPOSITION.TRUNCATE_AND_FLAG,
    basis: BASIS.PLAN_FROZEN,
    confirmed_by: CONFIRMATION.CONFIRMED,
    cited_from: 'stage2/IMPLEMENTATION-PLAN.md W9 deliverables',
    rationale:
      'The proj projection is the only thing --contains searches, so a silent truncation ' +
      'would make a search result quietly wrong. Overflow sets proj_truncated:true.',
  }),
  Object.freeze({
    id: 'proj_array_entries',
    value: 16,
    unit: 'entries per proj array field',
    surface: null,
    on_exceeded: DISPOSITION.TRUNCATE_AND_FLAG,
    basis: BASIS.PLAN_FROZEN,
    confirmed_by: CONFIRMATION.CONFIRMED,
    cited_from: 'stage2/IMPLEMENTATION-PLAN.md W9 deliverables',
    rationale: 'Same reason as proj_field_chars, for the array-valued projection fields.',
  }),
  Object.freeze({
    id: 'walk_entries',
    value: DEFAULT_WALK_CAP,
    unit: 'directory entries per walk',
    surface: null,
    on_exceeded: DISPOSITION.REPORT_OVERFLOW,
    basis: BASIS.MODULE_IMPORT,
    confirmed_by: CONFIRMATION.CONFIRMED,
    cited_from: 'engine/portfolio/inventory.mjs DEFAULT_WALK_CAP (W2)',
    rationale:
      'Imported rather than restated. The walk owns its own bound; duplicating the number ' +
      'here would create two ceilings that drift apart one edit at a time.',
  }),
]);

/** id -> value, for call sites that just want the number. */
export const CAPS = Object.freeze(
  Object.fromEntries(CAP_ENTRIES.map((entry) => [entry.id, entry.value])),
);

/** @param {string} id @returns {Readonly<object>|null} */
export function capEntry(id) {
  return CAP_ENTRIES.find((entry) => entry.id === id) ?? null;
}

/**
 * The warning threshold for a cap: 80% of the ceiling, rounded up so the warning always
 * fires strictly before the ceiling does.
 *
 * @param {string|number} idOrValue @returns {number}
 */
export function warningThreshold(idOrValue) {
  const value = typeof idOrValue === 'number' ? idOrValue : (capEntry(String(idOrValue))?.value ?? NaN);
  if (!Number.isFinite(value)) throw new Error(`caps: unknown cap ${JSON.stringify(idOrValue)}`);
  return Math.ceil(value * WARN_FRACTION);
}

/** Where an observed count sits against a cap. Not status codes: a load level. */
export const CAP_LEVEL = Object.freeze({
  WITHIN: 'WITHIN',
  WARNING: 'WARNING',
  AT_CEILING: 'AT_CEILING',
  BEYOND_CEILING: 'BEYOND_CEILING',
});

/**
 * @param {string} id @param {number} observed
 * @returns {{cap: string, value: number, observed: number, threshold: number, level: string,
 *            on_exceeded: string, warn: boolean, text: string}}
 */
export function capStatusFor(id, observed) {
  const entry = capEntry(id);
  if (entry === null) throw new Error(`caps: unknown cap ${JSON.stringify(id)}`);
  const threshold = warningThreshold(id);
  const count = Number(observed);
  const level = count > entry.value
    ? CAP_LEVEL.BEYOND_CEILING
    : count === entry.value
      ? CAP_LEVEL.AT_CEILING
      : count >= threshold
        ? CAP_LEVEL.WARNING
        : CAP_LEVEL.WITHIN;
  return Object.freeze({
    cap: entry.id,
    value: entry.value,
    observed: count,
    threshold,
    level,
    on_exceeded: entry.on_exceeded,
    warn: level !== CAP_LEVEL.WITHIN,
    text:
      `${entry.id}: ${count} of ${entry.value} ${entry.unit} ` +
      `(warning at ${threshold}, ${Math.round(WARN_FRACTION * 100)}% of the ceiling); ` +
      `at the ceiling the disposition is ${entry.on_exceeded}.`,
  });
}

// -- the volume-reachability classification ------------------------------------

/**
 * What can trigger a refusal on the query surface. DATA_VOLUME is deliberately IN the set:
 * a guard that cannot express the thing it forbids cannot prove it is absent.
 */
export const QUERY_REFUSAL_TRIGGER = Object.freeze({
  DATA_VOLUME: 'DATA_VOLUME',
  STORE_MISSING: 'STORE_MISSING',
  STORE_UNREADABLE: 'STORE_UNREADABLE',
  DAMAGED_BYTES: 'DAMAGED_BYTES',
  LOCK_CONTENTION: 'LOCK_CONTENTION',
  CURSOR_INVALIDATED: 'CURSOR_INVALIDATED',
  PATH_HAZARD_RECORDED: 'PATH_HAZARD_RECORDED',
  IDENTITY_AMBIGUOUS: 'IDENTITY_AMBIGUOUS',
  NO_MATCHES: 'NO_MATCHES',
  ROOT_NOT_LIVE: 'ROOT_NOT_LIVE',
});

/**
 * Every query-surface failure row, classified by what actually triggers it.
 *
 * This map is the guard's evidence. The claim "no query refusal is reachable by data
 * volume alone" is only checkable if every row on that surface has been looked at, so the
 * lint fails on an UNCLASSIFIED row as loudly as on a DATA_VOLUME one - otherwise a new
 * row could ship unexamined and the guard would report green over a gap.
 */
export const QUERY_REFUSAL_TRIGGERS = Object.freeze({
  QUERY_EMPTY_RECEIPT: QUERY_REFUSAL_TRIGGER.NO_MATCHES,
  QUERY_EMPTY_INSTRUMENT: QUERY_REFUSAL_TRIGGER.NO_MATCHES,
  QUERY_EMPTY_ROADMAP_EVENT: QUERY_REFUSAL_TRIGGER.NO_MATCHES,
  QUERY_UNKNOWN_RECEIPT: QUERY_REFUSAL_TRIGGER.ROOT_NOT_LIVE,
  QUERY_UNKNOWN_INSTRUMENT: QUERY_REFUSAL_TRIGGER.ROOT_NOT_LIVE,
  QUERY_UNKNOWN_ROADMAP_EVENT: QUERY_REFUSAL_TRIGGER.ROOT_NOT_LIVE,
  QUERY_INDEX_ABSENT: QUERY_REFUSAL_TRIGGER.STORE_MISSING,
  QUERY_INDEX_UNREACHABLE: QUERY_REFUSAL_TRIGGER.STORE_UNREADABLE,
  QUERY_LOCK_TIMEOUT: QUERY_REFUSAL_TRIGGER.LOCK_CONTENTION,
  QUERY_CURSOR_STALE: QUERY_REFUSAL_TRIGGER.CURSOR_INVALIDATED,
  QUERY_SNAPSHOT_UNPARSEABLE: QUERY_REFUSAL_TRIGGER.DAMAGED_BYTES,
  QUERY_PROJ_MOJIBAKE: QUERY_REFUSAL_TRIGGER.DAMAGED_BYTES,
  QUERY_TAIL_TORN: QUERY_REFUSAL_TRIGGER.DAMAGED_BYTES,
  QUERY_ROW_TAMPERED: QUERY_REFUSAL_TRIGGER.DAMAGED_BYTES,
  QUERY_IDENTITY_CONFLICT: QUERY_REFUSAL_TRIGGER.IDENTITY_AMBIGUOUS,
  QUERY_UNCLASSIFIED: QUERY_REFUSAL_TRIGGER.DAMAGED_BYTES,
  QUERY_INDEX_UNREADABLE: QUERY_REFUSAL_TRIGGER.STORE_UNREADABLE,
  QUERY_NO_MATCHES: QUERY_REFUSAL_TRIGGER.NO_MATCHES,
  QUERY_ROOT_UNKNOWN: QUERY_REFUSAL_TRIGGER.ROOT_NOT_LIVE,
  QUERY_SKIPPED_REPARSE: QUERY_REFUSAL_TRIGGER.PATH_HAZARD_RECORDED,
  QUERY_PATH_TOO_LONG: QUERY_REFUSAL_TRIGGER.PATH_HAZARD_RECORDED,
  QUERY_CASE_COLLISION: QUERY_REFUSAL_TRIGGER.PATH_HAZARD_RECORDED,
});

/** @returns {string[]} query rows whose refusal IS reachable by data volume. Must be empty. */
export function queryRefusalsReachableByVolume() {
  return Object.entries(QUERY_REFUSAL_TRIGGERS)
    .filter(([, trigger]) => trigger === QUERY_REFUSAL_TRIGGER.DATA_VOLUME)
    .map(([code]) => code)
    .sort();
}

/** @returns {string[]} query rows nobody has classified. Must be empty. */
export function unclassifiedQueryRows() {
  return rowsForSurface(SURFACE.QUERY)
    .map((row) => row.code)
    .filter((code) => !Object.prototype.hasOwnProperty.call(QUERY_REFUSAL_TRIGGERS, code))
    .sort();
}

/** @returns {string[]} classified codes that are not query rows at all. Must be empty. */
export function strayQueryClassifications() {
  const rows = new Set(rowsForSurface(SURFACE.QUERY).map((row) => row.code));
  return Object.keys(QUERY_REFUSAL_TRIGGERS).filter((code) => !rows.has(code)).sort();
}

/** @returns {string[]} caps on the query surface that refuse rather than page. Must be empty. */
export function queryCapsThatRefuse() {
  return CAP_ENTRIES
    .filter((entry) => entry.surface === SURFACE.QUERY && entry.on_exceeded === DISPOSITION.REFUSE)
    .map((entry) => entry.id)
    .sort();
}

/**
 * The caps table's own integrity, checked rather than assumed.
 *
 * @returns {string[]} problems, empty when the table is sound
 */
export function capsIntegrity() {
  const problems = [];
  const seen = new Set();
  for (const entry of CAP_ENTRIES) {
    if (seen.has(entry.id)) problems.push(`duplicate cap id: ${entry.id}`);
    seen.add(entry.id);
    if (!Number.isInteger(entry.value) || entry.value <= 0) {
      problems.push(`${entry.id}: value must be a positive integer, got ${entry.value}`);
    }
    if (!Object.values(DISPOSITION).includes(entry.on_exceeded)) {
      problems.push(`${entry.id}: ${entry.on_exceeded} is not a declared disposition`);
    }
    if (!Object.values(BASIS).includes(entry.basis)) {
      problems.push(`${entry.id}: ${entry.basis} is not a declared basis`);
    }
    if (!Object.values(CONFIRMATION).includes(entry.confirmed_by)) {
      problems.push(`${entry.id}: ${entry.confirmed_by} is not a declared confirmation state`);
    }
    if (typeof entry.cited_from !== 'string' || entry.cited_from.trim() === '') {
      problems.push(`${entry.id}: no citation - a cap whose basis is unstated is unpredictable`);
    }
    if (typeof entry.rationale !== 'string' || entry.rationale.trim() === '') {
      problems.push(`${entry.id}: no rationale`);
    }
    if (warningThreshold(entry.id) >= entry.value) {
      problems.push(`${entry.id}: the warning threshold does not precede the ceiling`);
    }
  }
  for (const code of unclassifiedQueryRows()) {
    problems.push(`${code}: a query-surface row with no declared trigger`);
  }
  for (const code of strayQueryClassifications()) {
    problems.push(`${code}: classified as a query row but absent from the failure table`);
  }
  for (const code of queryRefusalsReachableByVolume()) {
    problems.push(`${code}: a query refusal reachable by data volume alone`);
  }
  for (const id of queryCapsThatRefuse()) {
    problems.push(`${id}: a query-surface cap whose disposition is a refusal`);
  }
  return problems;
}

/** @returns {string} a table an operator or a document can read */
export function renderCapsMarkdown() {
  const lines = [
    '| cap | value | unit | on exceeded | warning at | basis | confirmed | cited from |',
    '|---|---:|---|---|---:|---|---|---|',
  ];
  for (const entry of CAP_ENTRIES) {
    lines.push(
      `| \`${entry.id}\` | ${entry.value} | ${entry.unit} | ${entry.on_exceeded} | ` +
      `${warningThreshold(entry.id)} | ${entry.basis} | ${entry.confirmed_by} | ${entry.cited_from} |`,
    );
  }
  return lines.join('\n');
}

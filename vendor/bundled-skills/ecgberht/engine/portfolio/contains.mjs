/**
 * W13 - the ONE --contains predicate, shared by the paged path and the full-scan oracle.
 *
 * WHY THIS IS A MODULE AND NOT TWO LOOPS. The completeness claim W13 has to make is that
 * paging to cursor exhaustion returns exactly the set a full scan returns. That claim is
 * only worth making if BOTH sides ask the same question of a row. Two `row.proj.title
 * .includes(needle)` loops written three hundred lines apart are two questions the first
 * time one of them learns about arrays, or about case, or about the truncation flag - and
 * the test would then be comparing a predicate against itself-with-a-bug and reporting
 * green. So the predicate is one exported function, and the pager and the oracle both call
 * it. That is the whole of "the predicate cannot fork".
 *
 * WHAT IS SEARCHED, AND WHAT IS DELIBERATELY NOT. `--contains` searches each class's `proj`
 * projection field set and nothing else - the field sets frozen in W9 and owned by
 * derive.mjs, imported here rather than restated, because a second copy of the field list is
 * a search that quietly stops covering a field the day W9 adds one. The row's path, its
 * hash, its class and its project_id are NOT searched: they are the row's identity, they are
 * matched by --project / --type, and folding them into a substring search would make
 * `--contains receipts` match every receipt in the portfolio by accident of the directory
 * name.
 *
 * THE TRUNCATION CAVEAT IS PART OF THE ANSWER. derive.mjs caps a `proj` string at
 * caps.proj_field_chars and sets `proj_truncated:true` rather than cutting in silence,
 * precisely so a search cannot be quietly wrong. This module carries that through: a row
 * whose projection was cut and which did NOT match is reported as a caveat, because "no
 * match" over cut content is a weaker statement than "no match" over whole content, and the
 * operator is the one entitled to know which they were handed.
 *
 * CASE. Matching is case-insensitive on both sides, via toLowerCase() after NFC
 * normalization - the same normalization the serializer uses, so a row that sorts one way
 * cannot match a different way.
 *
 * Stdlib only, and no I/O at all: this module cannot read a file even by accident.
 */

import { canonicalString } from './canonical.mjs';
import { PROJ_FIELDS, PROJ_TRUNCATED_FIELD } from './derive.mjs';
import { scanBytesForMojibake } from '../encoding.mjs';
import { ENCODING_STATUS } from '../encoding.mjs';

/** The predicate's frozen version. Changing WHAT is searched means contains-v2. */
export const CONTAINS_VERSION = 'contains-v1';

/** The classes that carry a `proj` projection, sorted, read from W9's frozen table. */
export const CONTAINS_CLASSES = Object.freeze(Object.keys(PROJ_FIELDS).sort());

/**
 * The field set searched for one class - W9's projection, not a list of its own.
 *
 * @param {string} className @returns {ReadonlyArray<string>} sorted; empty for an unknown class
 */
export function containsFieldsFor(className) {
  const fields = PROJ_FIELDS[String(className)];
  return fields === undefined ? Object.freeze([]) : Object.freeze([...fields].sort());
}

/**
 * The needle as it is compared: NFC-normalized and lowercased. An absent needle is null,
 * which means "no --contains filter was given" rather than "match the empty string" - and
 * the two must not be the same value, because one of them is a filter and one is not.
 *
 * @param {unknown} text @returns {string|null}
 */
export function normalizeNeedle(text) {
  if (text === null || text === undefined) return null;
  const value = canonicalString(text);
  return value === '' ? null : value.toLowerCase();
}

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Every searchable (field, value) pair on a row, flattened.
 *
 * Array-valued projection fields (receipt `subject_ids`) are flattened to one entry per
 * element with its index in the field name, so a match names the element that matched rather
 * than the array that contained it. A null - which is how derive.mjs records "the source did
 * not carry this field" - is skipped: it is an absence, and an absence matches nothing.
 *
 * @param {object} row a derived-row-v1 (or a body row derived from one)
 * @returns {ReadonlyArray<{field: string, value: string}>}
 */
export function projValuesOf(row) {
  const out = [];
  if (!isPlainObject(row)) return Object.freeze(out);
  const proj = isPlainObject(row.proj) ? row.proj : {};
  for (const field of containsFieldsFor(row.class)) {
    const value = proj[field];
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      value.forEach((entry, i) => {
        if (entry === null || entry === undefined) return;
        out.push(Object.freeze({ field: `${field}[${i}]`, value: canonicalString(entry) }));
      });
      continue;
    }
    out.push(Object.freeze({ field, value: canonicalString(value) }));
  }
  return Object.freeze(out);
}

/** @param {object} row @returns {boolean} whether this row's projection was capped */
export function projWasTruncated(row) {
  return isPlainObject(row) && row[PROJ_TRUNCATED_FIELD] === true;
}

/**
 * THE PREDICATE. Case-insensitive substring over the row's `proj` field set.
 *
 * @param {object} row @param {string|null} needle already normalized, or a raw string
 * @returns {Readonly<{matched: boolean, field: string|null, value: string|null,
 *          searched: ReadonlyArray<string>, truncated: boolean, filtered: boolean}>}
 */
export function containsMatch(row, needle) {
  const wanted = typeof needle === 'string' && needle === needle.toLowerCase() && needle !== ''
    ? needle
    : normalizeNeedle(needle);
  const searched = projValuesOf(row);
  const truncated = projWasTruncated(row);

  if (wanted === null) {
    // No filter given. Every row passes, and it passes for a stated reason rather than by
    // falling through a branch that happens to return true.
    return Object.freeze({
      matched: true,
      field: null,
      value: null,
      searched: Object.freeze(searched.map((s) => s.field)),
      truncated,
      filtered: false,
    });
  }

  for (const entry of searched) {
    if (entry.value.toLowerCase().includes(wanted)) {
      return Object.freeze({
        matched: true,
        field: entry.field,
        value: entry.value,
        searched: Object.freeze(searched.map((s) => s.field)),
        truncated,
        filtered: true,
      });
    }
  }

  return Object.freeze({
    matched: false,
    field: null,
    value: null,
    searched: Object.freeze(searched.map((s) => s.field)),
    truncated,
    filtered: true,
  });
}

/**
 * The boolean form, for a caller that only wants the verdict.
 *
 * @param {object} row @param {string|null} needle @returns {boolean}
 */
export function matchesContains(row, needle) {
  return containsMatch(row, needle).matched;
}

/**
 * Apply the predicate to a list, keeping the caveat the operator is entitled to.
 *
 * @param {ReadonlyArray<object>} rows @param {string|null} needle
 * @returns {Readonly<{rows: ReadonlyArray<object>, matched: number,
 *          truncated_unmatched: ReadonlyArray<object>, needle: string|null}>}
 */
export function selectByContains(rows, needle) {
  const wanted = normalizeNeedle(needle);
  const kept = [];
  const cut = [];
  for (const row of rows ?? []) {
    const verdict = containsMatch(row, wanted);
    if (verdict.matched) kept.push(row);
    else if (verdict.truncated) cut.push(row);
  }
  return Object.freeze({
    rows: Object.freeze(kept),
    matched: kept.length,
    // A row whose projection was cut AND which did not match: the one case where "not found"
    // may be an artifact of the cap rather than of the content.
    truncated_unmatched: Object.freeze(cut),
    needle: wanted,
  });
}

/**
 * Damage inside the searched region, named rather than searched over in silence.
 *
 * A `proj` field carrying UTF-8-read-as-CP1252 bytes will not match the word the operator
 * typed, because the word is not what is stored any more. The row is still returned - it is
 * real content - but the damage travels with it, which is the difference between a result
 * that is wrong and a result that says why.
 *
 * @param {object} row @returns {Readonly<{damaged: boolean, field: string|null,
 *          offset: number|null}>}
 */
export function mojibakeInProj(row) {
  for (const entry of projValuesOf(row)) {
    const scan = scanBytesForMojibake(Buffer.from(entry.value, 'utf8'));
    if (scan.status === ENCODING_STATUS.MOJIBAKE) {
      return Object.freeze({ damaged: true, field: entry.field, offset: scan.first_offset ?? 0 });
    }
  }
  return Object.freeze({ damaged: false, field: null, offset: null });
}

/** @returns {string} a one-line statement of what --contains searches, for help text */
export function describeContains() {
  return CONTAINS_CLASSES
    .map((className) => `${className}: ${containsFieldsFor(className).join(', ')}`)
    .join('; ');
}

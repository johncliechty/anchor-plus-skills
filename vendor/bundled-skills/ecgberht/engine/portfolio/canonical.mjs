/**
 * W6 - canonical.mjs: the ONE snapshot serializer, and the D-2 split enforced in code.
 *
 * WHY THIS FILE EXISTS. C1 says a deleted snapshot rebuilds byte-equal. FM-02 says the way
 * that claim dies is not one catastrophic mistake but a thousand small ones: a key emitted
 * in insertion order here, a `\r\n` from a text editor there, a project list in walk order,
 * a timestamp somebody needed "just for debugging". Each is individually harmless and
 * collectively fatal, and none of them fails a test on the day it is written. The defence is
 * not vigilance, it is a CHOKE POINT: exactly one function turns portfolio state into bytes,
 * and it refuses the inputs that would make the equality claim false.
 *
 * WHAT CANONICAL MEANS HERE, stated so nobody has to infer it from the code:
 *
 *   1. Key order. Inside `body` - whose key set is OPEN, because later waves add fields -
 *      keys are sorted lexicographically by UTF-16 code unit. Where W4 froze a CLOSED
 *      enumeration (the three top-level keys, the four freshness fields, the four
 *      per-project fields), keys are emitted in THAT frozen order, which is exactly as
 *      deterministic as a sort and keeps the declared schema id first, where a header
 *      belongs. The enumerations are imported from snapshot-shape.mjs rather than restated,
 *      so the order cannot drift from the field set it orders.
 *
 *   2. Object property order is never trusted. JavaScript orders integer-like keys ahead of
 *      string keys regardless of insertion, so building a "sorted" object and handing it to
 *      JSON.stringify silently produces unsorted bytes the moment a key looks like a number.
 *      This module therefore emits JSON itself, key by key, in an order it computed.
 *
 *   3. Array order. `projects` arrays are sorted by project_id; `rows` arrays are sorted by
 *      (project_id, class, path, seq) exactly as the plan freezes it, with path compared
 *      lowercased-then-raw so the ordering matches the NG-2 walk contract. Ties fall back to
 *      the child's own canonical text, so the sort is TOTAL: two rows that differ only in a
 *      field outside the sort key still land in a fixed order rather than wherever the input
 *      happened to put them (an identity conflict puts two entries under one project_id, and
 *      that is precisely when a partial order would produce two different bodies).
 *
 *   4. Strings are normalized to Unicode NFC. The same path, spelled decomposed on one host
 *      and composed on another, is one path; without normalization it is two different
 *      bodies for one logical state, and the difference is invisible in every diff tool.
 *
 *   5. LF only, and exactly one trailing newline. JSON escaping guarantees no raw CR or LF
 *      can reach the output from a value; the module asserts that rather than assuming it.
 *
 * THE D-2 SPLIT LIVES HERE. `body` is the canonical, clock-free, host-free region compared
 * byte for byte. `freshness` is the ONE named block permitted to vary - and this module
 * serializes it TOO, so it is key-ordered and byte-deterministic given its inputs. That is
 * the entire weakening D-2 permits: not "the artifact is partly nondeterministic" but "one
 * named block varies with its inputs, and even that block's bytes are a pure function of
 * them". A field outside the frozen freshness set is refused BY NAME, because the block is a
 * fence and not a junk drawer.
 *
 * WHAT IS NOT FLAGGED, and why - a lint that cries wolf gets switched off:
 *   - A UUID VALUE is not evidence of nondeterminism. project_id is a UUID, minted exactly
 *     once (W7) and thereafter a permanent fact; it belongs in `body`. What is
 *     nondeterministic is a field MINTED AT SERIALIZATION TIME, which is a property of the
 *     field's role - so generated-id detection is by field NAME, never by value shape.
 *   - An absolute path is not flagged either. W11's loud-unknown row carries a last-known
 *     path by contract, and flagging it would force that row to lie.
 *
 * BYTES LEAVE ONLY THROUGH W5. writeCanonicalSnapshot hands the finished text to
 * writeSnapshot (engine/portfolio/snapshot-write.mjs), the D-1 temp+rename primitive, and
 * always supplies the bytes, so the primitive never has occasion to serialize anything
 * itself. test/w49-canonical-purity.test.mjs fails any module that opens the snapshot for
 * writing outside the rebuilder and the D-3 re-materializer, or that reaches the write
 * primitive without coming through this file.
 *
 * Stdlib only.
 */

import crypto from 'node:crypto';
import os from 'node:os';

import {
  FRESHNESS_KEYS,
  PER_PROJECT_KEYS,
  SNAPSHOT_KEYS,
  SNAPSHOT_SCHEMA,
  emptyFreshnessBlock,
  formatSnapshotProblems,
  perProjectFreshness,
  validateFreshnessBlock,
} from './snapshot-shape.mjs';
import { writeSnapshot } from './snapshot-write.mjs';

/** The serializer's frozen version. */
export const CANONICAL_VERSION = 'canonical-v1';

/** The one line terminator. CRLF is a diff that is not a change, forever. */
export const NEWLINE = '\n';

/** The array keys whose order is imposed rather than accepted. */
export const PROJECTS_KEY = 'projects';
export const ROWS_KEY = 'rows';

/** The per-project freshness map's key inside the block. */
export const PER_PROJECT_FIELD = 'per_project';

/** The row sort key, in the plan's order: (project_id, class, path, seq). */
export const ROW_SORT_FIELDS = Object.freeze(['project_id', 'class', 'path', 'seq']);

/** The field a project entry is sorted by. */
export const PROJECT_SORT_FIELD = ROW_SORT_FIELDS[0];

// -- refusals ------------------------------------------------------------------

/** The refusals this module raises. Contract violations by the caller, all named. */
export const CANONICAL_REFUSAL = Object.freeze({
  BODY_NONDETERMINISTIC: 'CANONICAL_BODY_NONDETERMINISTIC',
  BODY_NOT_AN_OBJECT: 'CANONICAL_BODY_NOT_AN_OBJECT',
  FRESHNESS_NOT_FROZEN: 'CANONICAL_FRESHNESS_NOT_FROZEN',
  FRESHNESS_MALFORMED: 'CANONICAL_FRESHNESS_MALFORMED',
  SCHEMA_MISMATCH: 'CANONICAL_SCHEMA_MISMATCH',
  UNSUPPORTED_VALUE: 'CANONICAL_UNSUPPORTED_VALUE',
  NOT_LF_ONLY: 'CANONICAL_NOT_LF_ONLY',
});

/** Operator- and programmer-visible text for each refusal. */
export const CANONICAL_REFUSAL_TEXT = Object.freeze({
  [CANONICAL_REFUSAL.BODY_NONDETERMINISTIC]:
    'the snapshot body carries a value that will not be the same on the next rebuild. D-2 ' +
    'confines every clock-, host- and mint-varying value to the named freshness block; the ' +
    'block is not a defence for a field inside the body, it is the fence that keeps the ' +
    'body byte-equal.',
  [CANONICAL_REFUSAL.BODY_NOT_AN_OBJECT]:
    'the snapshot body must be a plain object. The body is the region byte-equality is ' +
    'asserted over, so its shape is part of the contract rather than a convenience.',
  [CANONICAL_REFUSAL.FRESHNESS_NOT_FROZEN]:
    'the freshness block carries a key outside the field set W4 froze. The block is the ONE ' +
    'region permitted to vary, which is precisely why it may not also be the region where ' +
    'anything at all may be stored.',
  [CANONICAL_REFUSAL.FRESHNESS_MALFORMED]:
    'the freshness block does not validate against its frozen shape, so the one region ' +
    'permitted to vary would vary in a way no reader has a contract for.',
  [CANONICAL_REFUSAL.SCHEMA_MISMATCH]:
    'the snapshot declares a schema id other than the derived index schema. The id is what ' +
    'marks this artifact DERIVED and therefore safe to delete and rebuild.',
  [CANONICAL_REFUSAL.UNSUPPORTED_VALUE]:
    'the value has no canonical JSON form. A serializer that guesses here produces bytes ' +
    'that depend on the guess, which is the thousand-cuts failure this module exists to stop.',
  [CANONICAL_REFUSAL.NOT_LF_ONLY]:
    'the serialized snapshot carries a carriage return or an interior newline. The frozen ' +
    'framing is LF-only with exactly one trailing newline.',
});

/** An error carrying its refusal code, its text and (where it has one) the offending field. */
export class CanonicalRefusal extends Error {
  /** @param {string} code @param {string} [detail] @param {Array<object>} [findings] */
  constructor(code, detail = '', findings = []) {
    const text = CANONICAL_REFUSAL_TEXT[code] ?? code;
    super(detail ? `${code}: ${text} (${detail})` : `${code}: ${text}`);
    this.name = 'CanonicalRefusal';
    this.code = code;
    this.text = text;
    this.detail = detail;
    this.findings = Object.freeze(findings.slice());
  }
}

// -- primitives ----------------------------------------------------------------

/** @param {unknown} v @returns {boolean} */
function isPlainObject(v) {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

/**
 * NFC, so one path is one string. Composed and decomposed spellings of the same characters
 * are the same path to every operator and to every filesystem that matters here; leaving
 * them distinct would mean two byte-different bodies for one logical state.
 *
 * @param {string} value @returns {string}
 */
export function canonicalString(value) {
  return String(value).normalize('NFC');
}

/** @param {unknown} a @param {unknown} b @returns {number} code-unit order, locale-free */
export function compareText(a, b) {
  const x = canonicalString(a ?? '');
  const y = canonicalString(b ?? '');
  if (x < y) return -1;
  return x > y ? 1 : 0;
}

/**
 * Path order: lowercased first, raw as the tie-break - the same rule the NG-2 walk contract
 * uses, so a row list and a walk cannot disagree about which of two case-colliding paths
 * comes first.
 *
 * @param {unknown} a @param {unknown} b @returns {number}
 */
export function comparePathText(a, b) {
  const x = canonicalString(a ?? '').toLowerCase();
  const y = canonicalString(b ?? '').toLowerCase();
  if (x < y) return -1;
  if (x > y) return 1;
  return compareText(a, b);
}

/** @param {unknown} a @param {unknown} b @returns {number} numbers ascending, non-numbers last */
export function compareNumeric(a, b) {
  const x = typeof a === 'number' && Number.isFinite(a) ? a : Number.POSITIVE_INFINITY;
  const y = typeof b === 'number' && Number.isFinite(b) ? b : Number.POSITIVE_INFINITY;
  if (x < y) return -1;
  return x > y ? 1 : 0;
}

/** @param {unknown} a @param {unknown} b @returns {number} projects by project_id */
export function compareProjects(a, b) {
  const left = isPlainObject(a) ? a[PROJECT_SORT_FIELD] : undefined;
  const right = isPlainObject(b) ? b[PROJECT_SORT_FIELD] : undefined;
  return compareText(left, right);
}

/**
 * Rows by (project_id, class, path, seq), which is the plan's frozen order.
 *
 * @param {unknown} a @param {unknown} b @returns {number}
 */
export function compareRows(a, b) {
  const [idField, classField, pathField, seqField] = ROW_SORT_FIELDS;
  const left = isPlainObject(a) ? a : {};
  const right = isPlainObject(b) ? b : {};
  return (
    compareText(left[idField], right[idField])
    || compareText(left[classField], right[classField])
    || comparePathText(left[pathField], right[pathField])
    || compareNumeric(left[seqField], right[seqField])
  );
}

/** @param {string} key @returns {((a: unknown, b: unknown) => number)|null} */
export function comparatorFor(key) {
  if (key === PROJECTS_KEY) return compareProjects;
  if (key === ROWS_KEY) return compareRows;
  return null;
}

// -- the nondeterminism scan ---------------------------------------------------

/** The kinds of nondeterminism the body scan names. */
export const NONDETERMINISM = Object.freeze({
  TIMESTAMP: 'nondeterministic-timestamp',
  HOSTNAME: 'nondeterministic-hostname',
  GENERATED_ID: 'nondeterministic-generated-id',
  UNSTABLE_VALUE: 'nondeterministic-value',
});

/**
 * Field names that are clocks by role. The suffix pattern catches the shapes this codebase
 * actually uses (`written_at`, `computed_at`, `*_ts`, `*_time`), and the explicit list
 * carries the ones no pattern would guess.
 */
export const CLOCK_FIELD_PATTERN = /^(?:.*_)?(?:at|ts|time|timestamp|date|clock|mtime|ctime|atime|birthtime|epoch)$/i;

/** Clock-by-role field names the pattern above does not describe. */
export const CLOCK_FIELD_NAMES = Object.freeze([
  'last_seen',
  'last_verified',
  'first_seen',
  'now',
  'today',
  'uptime',
  'elapsed_ms',
  'duration_ms',
]);

/** Field names that name the machine rather than the portfolio. */
export const HOST_FIELD_NAMES = Object.freeze([
  'host',
  'hostname',
  'machine',
  'machine_name',
  'computername',
  'computer_name',
  'node_name',
  'os_hostname',
]);

/**
 * Field names whose value is minted at serialization time.
 *
 * Deliberately absent: project_id, receipt_id, event_id, instrument_id, registration_receipt_id.
 * Those are minted ONCE and are then facts about the portfolio - the whole point of W7's
 * once-only identity is that they survive a rebuild unchanged.
 */
export const GENERATED_ID_FIELD_NAMES = Object.freeze([
  'uuid',
  'guid',
  'nonce',
  'random',
  'rand',
  'run_id',
  'session_id',
  'request_id',
  'correlation_id',
  'instance_id',
  'boot_id',
  'pid',
  'process_id',
  'tmp',
  'tmp_path',
  'temp_path',
]);

/** An ISO-8601-ish instant anywhere inside a string. */
export const ISO_INSTANT_PATTERN = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?/;

/** Epoch milliseconds at 2001-09-09T01:46:40Z: the floor for "this integer is a clock". */
export const EPOCH_MS_FLOOR = 1_000_000_000_000;

/** @param {string} name @returns {boolean} */
function isClockField(name) {
  const key = String(name).toLowerCase();
  return CLOCK_FIELD_NAMES.includes(key) || CLOCK_FIELD_PATTERN.test(key);
}

/** @param {string} name @returns {boolean} */
function isHostField(name) {
  return HOST_FIELD_NAMES.includes(String(name).toLowerCase());
}

/** @param {string} name @returns {boolean} */
function isGeneratedIdField(name) {
  return GENERATED_ID_FIELD_NAMES.includes(String(name).toLowerCase());
}

/** @param {unknown} value @param {string} host @returns {boolean} */
function namesThisMachine(value, host) {
  if (!host || typeof value !== 'string') return false;
  const lower = canonicalString(value).toLowerCase();
  return lower === host || lower.startsWith(`\\\\${host}\\`) || lower.startsWith(`//${host}/`);
}

/** @param {string} where @param {string} field @param {string} kind @param {string} detail @param {unknown} value */
function finding(where, field, kind, detail, value) {
  return Object.freeze({
    path: where,
    field,
    kind,
    value: typeof value === 'string' ? value : String(value),
    message: `${where} is ${kind}: ${detail}`,
  });
}

/**
 * Every nondeterministic value inside `body`, reported by field path AND kind.
 *
 * The report is a list rather than a boolean because the acceptance criterion is that the
 * lint NAMES the offending field: "the body is impure" sends an author hunting, and a
 * hunt is where the field quietly gets moved into the freshness block instead of removed.
 *
 * @param {unknown} value
 * @param {{hostname?: string, trail?: string}} [opts]
 * @returns {Array<{path: string, field: string, kind: string, value: string, message: string}>}
 */
export function scanForNondeterminism(value, opts = {}) {
  const host = canonicalString(opts.hostname ?? safeHostname()).toLowerCase();
  const found = [];

  const walk = (node, trail, field) => {
    if (node instanceof Date) {
      found.push(finding(
        trail, field, NONDETERMINISM.TIMESTAMP,
        'a Date object is a reading of the clock, and the body is the clock-free region',
        node.toISOString(),
      ));
      return;
    }
    if (typeof node === 'string') {
      if (ISO_INSTANT_PATTERN.test(node)) {
        found.push(finding(
          trail, field, NONDETERMINISM.TIMESTAMP,
          'the value is a wall-clock instant; D-2 confines wall clock to the freshness block',
          node,
        ));
      } else if (namesThisMachine(node, host)) {
        found.push(finding(
          trail, field, NONDETERMINISM.HOSTNAME,
          'the value names this machine, so the body would differ on the next machine',
          node,
        ));
      }
      return;
    }
    if (typeof node === 'number') {
      if (Number.isFinite(node) && Math.abs(node) >= EPOCH_MS_FLOOR) {
        found.push(finding(
          trail, field, NONDETERMINISM.TIMESTAMP,
          'the integer is large enough to be epoch milliseconds, which is a clock in disguise',
          node,
        ));
      } else if (!Number.isFinite(node)) {
        found.push(finding(
          trail, field, NONDETERMINISM.UNSTABLE_VALUE,
          'a non-finite number has no JSON form and would serialize as null',
          node,
        ));
      }
      return;
    }
    if (typeof node === 'function' || typeof node === 'symbol' || typeof node === 'bigint') {
      found.push(finding(
        trail, field, NONDETERMINISM.UNSTABLE_VALUE,
        `a ${typeof node} has no canonical JSON form`,
        String(node),
      ));
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((item, i) => walk(item, `${trail}[${i}]`, field));
      return;
    }
    if (node !== null && typeof node === 'object') {
      for (const key of Object.keys(node)) {
        const where = trail ? `${trail}.${key}` : key;
        if (isClockField(key)) {
          found.push(finding(
            where, key, NONDETERMINISM.TIMESTAMP,
            'the field is a clock by role, so it varies between two rebuilds of one state - '
            + 'and it varies whatever its value happens to be today',
            node[key],
          ));
        } else if (isHostField(key)) {
          found.push(finding(
            where, key, NONDETERMINISM.HOSTNAME,
            'the field names the machine, and the body is the host-free region',
            node[key],
          ));
        } else if (isGeneratedIdField(key)) {
          found.push(finding(
            where, key, NONDETERMINISM.GENERATED_ID,
            'the field is minted at write time, so a rebuild mints a different one',
            node[key],
          ));
        }
        walk(node[key], where, key);
      }
    }
  };

  walk(value, opts.trail ?? '', '');
  return found;
}

/** @returns {string} this machine's name, or '' where the platform refuses to say */
function safeHostname() {
  try {
    return os.hostname() || '';
  } catch {
    return '';
  }
}

/** @param {unknown} body @param {{hostname?: string}} [opts] @returns {boolean} */
export function isPureBody(body, opts = {}) {
  return scanForNondeterminism(body, { ...opts, trail: 'body' }).length === 0;
}

/**
 * Refuse a body that is not a pure function of portfolio state.
 *
 * @param {unknown} body @param {{hostname?: string}} [opts]
 * @returns {unknown} body, unchanged, so the assertion can wrap an argument
 */
export function assertPureBody(body, opts = {}) {
  const findings = scanForNondeterminism(body, { ...opts, trail: 'body' });
  if (findings.length > 0) {
    const first = findings[0];
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.BODY_NONDETERMINISTIC,
      `${first.message}${findings.length > 1 ? ` (and ${findings.length - 1} more)` : ''}`,
      findings,
    );
  }
  return body;
}

// -- the emitter ---------------------------------------------------------------

/** @param {string} key @returns {string} the key as a JSON string */
function quote(key) {
  return JSON.stringify(canonicalString(key));
}

/**
 * Emit one value as canonical JSON.
 *
 * The emitter never relies on JavaScript's own property order: it computes the key order and
 * writes the object itself. That is the difference between "we sorted the keys" and "the
 * bytes are sorted", and an integer-like key is where the two part company.
 *
 * @param {unknown} value @param {string} [key] the key this value sits under, for array order
 * @param {string} [trail] the field path, for a refusal that names the field
 * @returns {string}
 */
export function emitCanonical(value, key = '', trail = '') {
  const where = trail || '(root)';

  if (value === null) return 'null';
  if (value === undefined) {
    throw new CanonicalRefusal(CANONICAL_REFUSAL.UNSUPPORTED_VALUE, `${where} is undefined`);
  }

  const type = typeof value;
  if (type === 'boolean') return value ? 'true' : 'false';
  if (type === 'number') {
    if (!Number.isFinite(value)) {
      throw new CanonicalRefusal(
        CANONICAL_REFUSAL.UNSUPPORTED_VALUE,
        `${where} is a non-finite number, which JSON would silently write as null`,
      );
    }
    return JSON.stringify(value === 0 ? 0 : value);
  }
  if (type === 'string') return JSON.stringify(canonicalString(value));
  if (type === 'bigint' || type === 'function' || type === 'symbol') {
    throw new CanonicalRefusal(CANONICAL_REFUSAL.UNSUPPORTED_VALUE, `${where} is a ${type}`);
  }

  if (value instanceof Date) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.UNSUPPORTED_VALUE,
      `${where} is a Date; a serializer that renders one has decided a clock format on the `
      + "caller's behalf",
    );
  }

  if (Array.isArray(value)) {
    const items = value.map((item, i) => ({
      item,
      text: emitCanonical(item, '', `${where}[${i}]`),
    }));
    const compare = comparatorFor(key);
    if (compare !== null) {
      // The child's own canonical text is the tie-break, so the order is TOTAL: two entries
      // equal on the sort key still land in a fixed order rather than in input order.
      items.sort((a, b) => compare(a.item, b.item) || compareText(a.text, b.text));
    }
    return `[${items.map((entry) => entry.text).join(',')}]`;
  }

  if (isPlainObject(value)) {
    const keys = Object.keys(value)
      .filter((k) => value[k] !== undefined)
      .sort(compareText);
    const parts = keys.map(
      (k) => `${quote(k)}:${emitCanonical(value[k], k, trail ? `${trail}.${k}` : k)}`,
    );
    return `{${parts.join(',')}}`;
  }

  throw new CanonicalRefusal(
    CANONICAL_REFUSAL.UNSUPPORTED_VALUE,
    `${where} is a ${Object.prototype.toString.call(value)}, which has no canonical JSON form`,
  );
}

/**
 * The canonical text of a value, with no trailing newline. Exported because a caller
 * hashing a region needs the same bytes the snapshot carries, not a second stringify.
 *
 * @param {unknown} value @returns {string}
 */
export function canonicalJson(value) {
  return emitCanonical(value, '', '');
}

// -- the two regions -----------------------------------------------------------

/**
 * The canonical text of the `body` region: pure, key-sorted, order-imposed.
 *
 * @param {unknown} body @param {{hostname?: string}} [opts] @returns {string}
 */
export function canonicalBodyText(body, opts = {}) {
  if (!isPlainObject(body)) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.BODY_NOT_AN_OBJECT,
      `got ${Array.isArray(body) ? 'an array' : typeof body}`,
    );
  }
  assertPureBody(body, opts);
  return emitCanonical(body, '', 'body');
}

/**
 * Normalize the freshness block: unknown keys refused by name, absent keys filled from the
 * frozen defaults, and the result validated against W4's shape before a byte is emitted.
 *
 * @param {unknown} block @returns {object}
 */
export function canonicalFreshness(block = {}) {
  if (!isPlainObject(block)) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.FRESHNESS_MALFORMED,
      `the block is ${Array.isArray(block) ? 'an array' : typeof block}, not an object`,
    );
  }

  for (const key of Object.keys(block)) {
    if (!FRESHNESS_KEYS.includes(key)) {
      throw new CanonicalRefusal(
        CANONICAL_REFUSAL.FRESHNESS_NOT_FROZEN,
        `freshness.${key} is outside the frozen set (${FRESHNESS_KEYS.join(', ')})`,
      );
    }
  }

  const filled = emptyFreshnessBlock(block);
  const perProject = filled[PER_PROJECT_FIELD];
  if (!isPlainObject(perProject)) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.FRESHNESS_MALFORMED,
      `freshness.${PER_PROJECT_FIELD} is not an object`,
    );
  }

  const entries = {};
  for (const projectId of Object.keys(perProject)) {
    const entry = perProject[projectId];
    if (!isPlainObject(entry)) {
      throw new CanonicalRefusal(
        CANONICAL_REFUSAL.FRESHNESS_MALFORMED,
        `freshness.${PER_PROJECT_FIELD}.${projectId} is not an object`,
      );
    }
    for (const key of Object.keys(entry)) {
      if (!PER_PROJECT_KEYS.includes(key)) {
        throw new CanonicalRefusal(
          CANONICAL_REFUSAL.FRESHNESS_NOT_FROZEN,
          `freshness.${PER_PROJECT_FIELD}.${projectId}.${key} is outside the frozen set `
          + `(${PER_PROJECT_KEYS.join(', ')})`,
        );
      }
    }
    entries[projectId] = perProjectFreshness(entry);
  }

  const normalized = { ...filled, [PER_PROJECT_FIELD]: entries };
  const check = validateFreshnessBlock(normalized);
  if (!check.ok) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.FRESHNESS_MALFORMED,
      formatSnapshotProblems(check.problems).trim(),
    );
  }
  return normalized;
}

/**
 * The canonical text of the `freshness` region.
 *
 * Key order here comes from W4's frozen enumeration rather than from a sort, for one
 * reason: the field set is CLOSED, so the enumeration is as deterministic as a sort and it
 * keeps the block in the order the contract states it in. The per-project MAP is keyed by
 * project_id, which is open data, so those keys are sorted.
 *
 * @param {unknown} block @returns {string}
 */
export function canonicalFreshnessText(block = {}) {
  const normalized = canonicalFreshness(block);
  const parts = FRESHNESS_KEYS.map((key) => {
    if (key !== PER_PROJECT_FIELD) {
      return `${quote(key)}:${emitCanonical(normalized[key], key, `freshness.${key}`)}`;
    }
    const map = normalized[PER_PROJECT_FIELD];
    const ids = Object.keys(map).sort(compareText);
    const rendered = ids.map((id) => {
      const entry = map[id];
      const fields = PER_PROJECT_KEYS.map(
        (f) => `${quote(f)}:${emitCanonical(entry[f], f, `freshness.${PER_PROJECT_FIELD}.${id}.${f}`)}`,
      );
      return `${quote(id)}:{${fields.join(',')}}`;
    });
    return `${quote(key)}:{${rendered.join(',')}}`;
  });
  return `{${parts.join(',')}}`;
}

// -- the snapshot --------------------------------------------------------------

/** @param {string} text @returns {string} the sha256 of the bytes as they hit the disk */
export function snapshotSha256(text) {
  return crypto.createHash('sha256').update(Buffer.from(String(text), 'utf8')).digest('hex');
}

/**
 * Serialize a whole snapshot.
 *
 * @param {{schema?: string, body?: object, freshness?: object}} [parts]
 * @param {{hostname?: string}} [opts]
 * @returns {Readonly<{schema: string, snapshot: object, text: string, body_text: string,
 *                     freshness_text: string, byte_len: number, sha256: string}>}
 */
export function serializeSnapshot(parts = {}, opts = {}) {
  if (parts.schema !== undefined && parts.schema !== SNAPSHOT_SCHEMA) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.SCHEMA_MISMATCH,
      `expected ${SNAPSHOT_SCHEMA}, got ${JSON.stringify(parts.schema)}`,
    );
  }

  const bodyText = canonicalBodyText(parts.body ?? {}, opts);
  const freshnessText = canonicalFreshnessText(parts.freshness ?? {});
  const regions = {
    schema: JSON.stringify(SNAPSHOT_SCHEMA),
    body: bodyText,
    freshness: freshnessText,
  };

  // The three top-level keys are emitted in W4's frozen order, so the declared schema id is
  // the first thing in the file. A header that arrives after the payload is not a header.
  const text = `{${SNAPSHOT_KEYS.map((key) => `${quote(key)}:${regions[key]}`).join(',')}}${NEWLINE}`;
  assertLfFramed(text);

  return Object.freeze({
    schema: SNAPSHOT_SCHEMA,
    snapshot: JSON.parse(text),
    text,
    body_text: bodyText,
    freshness_text: freshnessText,
    byte_len: Buffer.byteLength(text, 'utf8'),
    sha256: snapshotSha256(text),
  });
}

/**
 * The frozen framing, asserted rather than assumed: no CR anywhere, and exactly one LF, at
 * the end. JSON escaping guarantees both; a serializer that trusted the guarantee instead of
 * checking it is how a CRLF-normalizing editor or a stray concatenation ships unnoticed.
 *
 * @param {string} text @returns {string} text, unchanged
 */
export function assertLfFramed(text) {
  const value = String(text);
  if (value.includes('\r')) {
    throw new CanonicalRefusal(CANONICAL_REFUSAL.NOT_LF_ONLY, 'the text carries a carriage return');
  }
  if (!value.endsWith(NEWLINE) || value.indexOf(NEWLINE) !== value.length - 1) {
    throw new CanonicalRefusal(
      CANONICAL_REFUSAL.NOT_LF_ONLY,
      'the text must carry exactly one newline, as its final byte',
    );
  }
  return value;
}

/**
 * The canonical snapshot OBJECT - the same value the bytes parse back to.
 *
 * @param {{schema?: string, body?: object, freshness?: object}} [parts]
 * @param {{hostname?: string}} [opts] @returns {object}
 */
export function canonicalSnapshot(parts = {}, opts = {}) {
  return serializeSnapshot(parts, opts).snapshot;
}

/**
 * Split canonical text back into its two regions.
 *
 * This is what lets D-2 be CHECKED rather than promised: two snapshots of one logical state,
 * computed at different wall-clock times, are compared by asserting body_text is equal and
 * that removing the freshness region leaves identical text. Anything else that differed
 * would survive that subtraction and show up.
 *
 * @param {string} text @returns {{schema: unknown, body_text: string, freshness_text: string}}
 */
export function splitCanonicalText(text) {
  const doc = JSON.parse(String(text));
  return {
    schema: doc.schema,
    body_text: emitCanonical(doc.body, '', 'body'),
    freshness_text: canonicalFreshnessText(doc.freshness ?? {}),
  };
}

/**
 * Serialize and make durable - the ONLY route from portfolio state to bytes on disk.
 *
 * The bytes are handed to the W5 temp+rename primitive already canonical, so the primitive
 * never composes any of its own: D-1 owns durability, W6 owns byte order, and neither can
 * quietly absorb the other's guarantee.
 *
 * @param {string} snapshotPath
 * @param {{schema?: string, body?: object, freshness?: object}} parts
 * @param {{fsx?: object, seq?: number, pid?: number, retries?: number, hostname?: string}} [opts]
 * @returns {Readonly<object>} the primitive's outcome, plus the canonical hash and length
 */
export function writeCanonicalSnapshot(snapshotPath, parts, opts = {}) {
  const canonical = serializeSnapshot(parts, opts);
  const outcome = writeSnapshot(snapshotPath, canonical.snapshot, {
    ...opts,
    bytes: canonical.text,
  });
  return Object.freeze({
    ...outcome,
    sha256: canonical.sha256,
    byte_len: canonical.byte_len,
    canonical,
  });
}

/** The declared derived schema id, re-exported so a caller needs one import to write one file. */
export { SNAPSHOT_SCHEMA, FRESHNESS_KEYS, PER_PROJECT_KEYS, SNAPSHOT_KEYS };

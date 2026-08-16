/**
 * W4 - marker-v2: the in-root identity file, and the only reason recovery is git-free.
 *
 * WHY THIS FILE EXISTS. The disaster path (W17) is "the live log is gone". What survives
 * a lost log is what is lying on disk in plain working-tree bytes, and for identity that
 * is exactly one artifact: `<root>/.steward/project.json`. Every field recover-log
 * reconstructs about membership is read out of this file - see the field-source table in
 * planning/steward-tracking-2026-07/stage2/marker-v2-field-sources.md, where no
 * reconstructed field is allowed to exist without a named byte source the verb can read
 * without git. That is why the schema is frozen here in W4, before anything writes one:
 * a field added later is a field the already-written markers do not carry, and recovery
 * cannot invent it.
 *
 * WHAT IS DELIBERATELY NOT DEFAULTED. A marker missing `registration_receipt_id` is
 * REFUSED, with an integrity code from STATUS-v1 and the failure row that owns the case
 * (RECONCILE_MARKER_UNPARSEABLE, whose frozen text is "refused rather than defaulted,
 * because a defaulted identity is a forged one"). Defaulting a missing identity field is
 * the single most tempting shortcut on this surface and the one with the worst blast
 * radius: it turns "this claim is incomplete" into "this claim is fine", and the forged
 * claim then travels into a reconcile that rebinds a project to the wrong directory.
 *
 * THE FIELD SET IS CLOSED. An unknown key is refused rather than ignored. Ignoring extra
 * keys sounds tolerant and is not: it means a marker written by a future version - or by
 * a hand-editor - can carry a field this engine silently drops on the next write, and the
 * loss is invisible. Extending the marker means marker-v3 and a ratification, exactly as
 * inventory-v1 works.
 *
 * WHAT A MARKER IS NOT. It is not an index home (home.mjs never reads a marker), it is
 * not a store, and it is not authoritative over the log: NATIVE registration events are.
 * The marker is a MIRROR that makes the log's identity claims recoverable from bytes when
 * the log is gone, and a CLAIM that reconcile weighs - never a claim it obeys. A marker
 * that could bind by itself is a marker a byte-copy could forge, which is precisely the
 * NG-3 hazard identity.mjs classifies.
 *
 * Stdlib only.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { isValidUtf8, scanBytesForMojibake } from '../encoding.mjs';
import { writeFileAtomicSync } from '../durable-write.mjs';
import { CLASS, inventoryEntryFor, openablePath } from './inventory.mjs';
import { INTEGRITY, PRESENCE, assertIntegrityCode, assertStatusCode } from './status.mjs';

/** The frozen schema id. It is a VALUE in the file, so a v3 file is detectable as v3. */
export const MARKER_SCHEMA = 'steward-marker-v2';

/** The marker's location under a project root, read from the inventory-v1 entry. */
const MARKER_ENTRY = inventoryEntryFor(CLASS.IDENTITY_MARKER);

/** `.steward` - the directory the marker lives in, taken from inventory-v1. */
export const MARKER_DIR = MARKER_ENTRY.dir;

/** `project.json` - the marker file name, taken from inventory-v1. */
export const MARKER_FILE = MARKER_ENTRY.file;

/**
 * The CLOSED field set, in canonical order. This array is also the JSON.stringify
 * replacer, so the serialized key order cannot drift from the declared order.
 */
export const MARKER_FIELDS = Object.freeze([
  'schema',
  'project_id',
  'registered_at',
  'registered_path',
  'registration_receipt_id',
]);

/** The fields a marker may never omit. All of them: none is optional. */
export const MARKER_REQUIRED_FIELDS = MARKER_FIELDS;

/** The closed-set contract, where code can read it rather than a comment. */
export const MARKER_EXTENSION_GATE = Object.freeze({
  closed: true,
  version: MARKER_SCHEMA,
  next_version: 'steward-marker-v3',
  how_to_extend:
    'A new field means a new schema id and a ratification entry: markers already on disk ' +
    'cannot grow a field retroactively, and recover-log can only reconstruct what the ' +
    'bytes already carry.',
});

/** Every refusal this module raises, each mapped to STATUS-v1 and to a failure row. */
export const MARKER_REFUSAL = Object.freeze({
  ABSENT: 'MARKER_ABSENT',
  UNREADABLE: 'MARKER_UNREADABLE',
  EMPTY: 'MARKER_EMPTY',
  INVALID_UTF8: 'MARKER_INVALID_UTF8',
  MOJIBAKE: 'MARKER_MOJIBAKE',
  NOT_JSON: 'MARKER_NOT_JSON',
  NOT_AN_OBJECT: 'MARKER_NOT_AN_OBJECT',
  SCHEMA_MISMATCH: 'MARKER_SCHEMA_MISMATCH',
  FIELD_MISSING: 'MARKER_FIELD_MISSING',
  FIELD_MALFORMED: 'MARKER_FIELD_MALFORMED',
  UNKNOWN_FIELD: 'MARKER_UNKNOWN_FIELD',
  ALREADY_PRESENT: 'MARKER_ALREADY_PRESENT',
});

/**
 * refusal -> {status, failure_row}. The STATUS-v1 code is what surfaces render; the row
 * is the frozen W3 table entry that owns the user-visible sentence, so this module points
 * at that sentence instead of writing a second one that can drift from it.
 */
export const MARKER_STATUS = Object.freeze({
  [MARKER_REFUSAL.ABSENT]: Object.freeze({ status: PRESENCE.ABSENT, failure_row: 'RECONCILE_MARKER_ABSENT' }),
  [MARKER_REFUSAL.UNREADABLE]: Object.freeze({ status: PRESENCE.UNREACHABLE, failure_row: 'RECONCILE_REGISTRY_UNREADABLE' }),
  [MARKER_REFUSAL.EMPTY]: Object.freeze({ status: INTEGRITY.EMPTY, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.INVALID_UTF8]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.MOJIBAKE]: Object.freeze({ status: INTEGRITY.MOJIBAKE, failure_row: 'RECONCILE_MARKER_MOJIBAKE' }),
  [MARKER_REFUSAL.NOT_JSON]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.NOT_AN_OBJECT]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.SCHEMA_MISMATCH]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.FIELD_MISSING]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.FIELD_MALFORMED]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.UNKNOWN_FIELD]: Object.freeze({ status: INTEGRITY.UNPARSEABLE, failure_row: 'RECONCILE_MARKER_UNPARSEABLE' }),
  [MARKER_REFUSAL.ALREADY_PRESENT]: Object.freeze({ status: INTEGRITY.IDENTITY_CONFLICT, failure_row: 'RECONCILE_TWO_PLACES' }),
});

/** RFC-4122 shape, lowercase. Lowercase matters: one id must have exactly one spelling. */
export const PROJECT_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The nil UUID is a placeholder, never an identity. */
const NIL_PROJECT_ID = '00000000-0000-0000-0000-000000000000';

/** ISO-8601, UTC, seconds or milliseconds. Wall clock here is a RECORD, never an order. */
export const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;

/** @param {string} rootAbs @returns {string} the marker path under a project root */
export function markerPathFor(rootAbs) {
  return path.join(path.resolve(String(rootAbs)), MARKER_DIR, MARKER_FILE);
}

/** @param {string} code @param {string} field @param {string} detail @returns {object} */
function problem(code, field, detail) {
  const mapped = MARKER_STATUS[code];
  return Object.freeze({
    code,
    field,
    detail,
    status: assertStatusCode(mapped.status, `marker refusal ${code}`),
    failure_row: mapped.failure_row,
    text: `${code}: ${detail}`,
  });
}

/** @param {unknown} v @returns {boolean} */
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

/**
 * Validate a candidate marker OBJECT (already parsed).
 *
 * Every problem is reported, not just the first: an operator fixing a hand-written marker
 * should learn everything wrong with it in one pass rather than one field per run.
 *
 * @param {unknown} value
 * @param {{expect_registered_path?: string}} [opts]
 * @returns {{ok: boolean, marker: object|null, problems: Array<object>}}
 */
export function validateMarker(value, opts = {}) {
  const problems = [];

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    problems.push(problem(
      MARKER_REFUSAL.NOT_AN_OBJECT,
      '',
      `a marker is a JSON object; got ${Array.isArray(value) ? 'an array' : typeof value}`,
    ));
    return { ok: false, marker: null, problems: Object.freeze(problems) };
  }

  const record = /** @type {Record<string, unknown>} */ (value);

  for (const key of Object.keys(record)) {
    if (!MARKER_FIELDS.includes(key)) {
      problems.push(problem(
        MARKER_REFUSAL.UNKNOWN_FIELD,
        key,
        `${MARKER_SCHEMA} is a closed field set and carries no '${key}'; extending it means ` +
          `${MARKER_EXTENSION_GATE.next_version} and a ratification, not an extra key`,
      ));
    }
  }

  for (const field of MARKER_REQUIRED_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, field) || record[field] === undefined) {
      problems.push(problem(
        MARKER_REFUSAL.FIELD_MISSING,
        field,
        `${field} is absent; it is refused rather than defaulted, because a defaulted ` +
          'identity field is a forged claim about which project these bytes belong to',
      ));
    }
  }

  if (Object.prototype.hasOwnProperty.call(record, 'schema') && record.schema !== undefined) {
    if (record.schema !== MARKER_SCHEMA) {
      problems.push(problem(
        MARKER_REFUSAL.SCHEMA_MISMATCH,
        'schema',
        `expected ${MARKER_SCHEMA}, got ${JSON.stringify(record.schema)}`,
      ));
    }
  }

  const id = record.project_id;
  if (id !== undefined) {
    if (!isNonEmptyString(id)) {
      problems.push(problem(MARKER_REFUSAL.FIELD_MALFORMED, 'project_id', 'not a non-empty string'));
    } else if (!PROJECT_ID_PATTERN.test(/** @type {string} */ (id))) {
      problems.push(problem(
        MARKER_REFUSAL.FIELD_MALFORMED,
        'project_id',
        `${JSON.stringify(id)} is not a lowercase RFC-4122 identifier; ids are minted once by ` +
          'the register verb and are never composed from a path or a name',
      ));
    } else if (id === NIL_PROJECT_ID) {
      problems.push(problem(MARKER_REFUSAL.FIELD_MALFORMED, 'project_id', 'the nil id is a placeholder, not an identity'));
    }
  }

  const at = record.registered_at;
  if (at !== undefined) {
    if (!isNonEmptyString(at) || !TIMESTAMP_PATTERN.test(String(at)) || Number.isNaN(Date.parse(String(at)))) {
      problems.push(problem(
        MARKER_REFUSAL.FIELD_MALFORMED,
        'registered_at',
        `${JSON.stringify(at)} is not an ISO-8601 UTC instant; it is a record of when the id ` +
          'was minted and never an ordering key (the log sequence is the sole total order)',
      ));
    }
  }

  const registeredPath = record.registered_path;
  if (registeredPath !== undefined) {
    if (!isNonEmptyString(registeredPath)) {
      problems.push(problem(MARKER_REFUSAL.FIELD_MALFORMED, 'registered_path', 'not a non-empty string'));
    } else if (!path.isAbsolute(String(registeredPath))) {
      problems.push(problem(
        MARKER_REFUSAL.FIELD_MALFORMED,
        'registered_path',
        'must be the absolute path the root had at registration; a relative value could not ' +
          'be compared with the directory the marker was later found in',
      ));
    }
  }

  const receiptId = record.registration_receipt_id;
  if (receiptId !== undefined && !isNonEmptyString(receiptId)) {
    problems.push(problem(MARKER_REFUSAL.FIELD_MALFORMED, 'registration_receipt_id', 'not a non-empty string'));
  }

  if (problems.length > 0) {
    return { ok: false, marker: null, problems: Object.freeze(problems) };
  }

  const marker = Object.freeze({
    schema: MARKER_SCHEMA,
    project_id: String(record.project_id),
    registered_at: String(record.registered_at),
    registered_path: String(record.registered_path),
    registration_receipt_id: String(record.registration_receipt_id),
  });

  return { ok: true, marker, problems: Object.freeze([]) };
}

/**
 * Build a marker from its parts, validating on the way out. There is no path from an
 * invalid marker object to bytes on disk.
 *
 * @param {{project_id: string, registered_at: string, registered_path: string,
 *          registration_receipt_id: string}} parts
 * @returns {object} the frozen marker
 */
export function newMarker(parts) {
  const candidate = {
    schema: MARKER_SCHEMA,
    project_id: parts ? parts.project_id : undefined,
    registered_at: parts ? parts.registered_at : undefined,
    registered_path: parts && parts.registered_path !== undefined
      ? path.resolve(String(parts.registered_path))
      : undefined,
    registration_receipt_id: parts ? parts.registration_receipt_id : undefined,
  };
  const result = validateMarker(candidate);
  if (!result.ok) {
    throw new Error(`${MARKER_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return result.marker;
}

/**
 * The marker's canonical bytes: declared key order, two-space indent, LF, one trailing
 * newline. Deterministic because the hash W12 records over a marker must be reproducible
 * from the same fields on any machine.
 *
 * @param {object} marker @returns {string}
 */
export function markerText(marker) {
  const result = validateMarker(marker);
  if (!result.ok) {
    throw new Error(`${MARKER_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return `${JSON.stringify(result.marker, MARKER_FIELDS.slice(), 2).replace(/\r\n/g, '\n')}\n`;
}

/** @param {object|string} input a marker object or its exact bytes @returns {string} sha256 hex */
export function markerHash(input) {
  const text = typeof input === 'string' ? input : markerText(input);
  return crypto.createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex');
}

/**
 * Read and validate the marker under a project root.
 *
 * Never throws for a state the portfolio has a name for: an absent marker, an unreadable
 * one, a damaged one and a valid one all come back as a result object carrying a STATUS-v1
 * code. A root with no marker is a fact about that root, not an exception.
 *
 * @param {string} rootAbs
 * @param {{fs?: object}} [opts]
 * @returns {{ok: boolean, path: string, root: string, marker: object|null, status: string,
 *            code: string|null, failure_row: string|null, problems: Array<object>,
 *            bytes_len: number|null, hash: string|null}}
 */
export function readMarker(rootAbs, opts = {}) {
  const fsx = opts.fs ?? fs;
  const root = path.resolve(String(rootAbs));
  const markerPath = markerPathFor(root);

  const fail = (code, detail, extra = {}) => {
    const p = problem(code, '', detail);
    return {
      ok: false,
      path: markerPath,
      root,
      marker: null,
      status: p.status,
      code,
      failure_row: p.failure_row,
      problems: Object.freeze([p]),
      bytes_len: null,
      hash: null,
      ...extra,
    };
  };

  let bytes;
  try {
    // encoding-lint: raw-bytes - INVALID_UTF8 and MOJIBAKE are DISTINCT named states and a
    // decoded read erases both, so the bytes are read undecoded and decoded deliberately.
    bytes = fsx.readFileSync(openablePath(markerPath));
  } catch (err) {
    const code = err && err.code === 'ENOENT' ? MARKER_REFUSAL.ABSENT : MARKER_REFUSAL.UNREADABLE;
    return fail(
      code,
      code === MARKER_REFUSAL.ABSENT
        ? `no marker at ${markerPath}; this root carries no claim of identity`
        : `the marker at ${markerPath} could not be read (${err && err.code ? err.code : String(err)})`,
    );
  }

  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
  if (buffer.length === 0) {
    return fail(MARKER_REFUSAL.EMPTY, `the marker at ${markerPath} is zero bytes`);
  }
  if (!isValidUtf8(buffer)) {
    return fail(MARKER_REFUSAL.INVALID_UTF8, `the marker at ${markerPath} does not decode as UTF-8`);
  }

  const scan = scanBytesForMojibake(buffer);
  if (!scan.clean) {
    return fail(
      MARKER_REFUSAL.MOJIBAKE,
      `the marker at ${markerPath} carries encoding damage at byte ${scan.first_offset}`,
    );
  }

  let parsed;
  try {
    parsed = JSON.parse(buffer.toString('utf8'));
  } catch (err) {
    return fail(MARKER_REFUSAL.NOT_JSON, `the marker at ${markerPath} is not parseable JSON (${err.message})`);
  }

  const result = validateMarker(parsed);
  if (!result.ok) {
    const first = result.problems[0];
    return {
      ok: false,
      path: markerPath,
      root,
      marker: null,
      status: first.status,
      code: first.code,
      failure_row: first.failure_row,
      problems: result.problems,
      bytes_len: buffer.length,
      hash: null,
    };
  }

  return {
    ok: true,
    path: markerPath,
    root,
    marker: result.marker,
    status: assertIntegrityCode(INTEGRITY.OK, 'readMarker'),
    code: null,
    failure_row: null,
    problems: Object.freeze([]),
    bytes_len: buffer.length,
    hash: markerHash(buffer.toString('utf8')),
  };
}

/**
 * Write a marker into a project root.
 *
 * Refuses when one is already there. That refusal is the engine-side half of W7's
 * REGISTER_ALREADY_MARKED: a second write would either mint a second identity for one
 * root or overwrite the only git-free record of the first, and both are unrecoverable in
 * exactly the disaster this file exists for. `replace` is offered for W12's explicit
 * --claim route and for nothing else; it is never reached by a default code path.
 *
 * @param {string} rootAbs
 * @param {object} marker
 * @param {{replace?: boolean}} [opts]
 * @returns {{path: string, hash: string, bytes_len: number, replaced: boolean}}
 */
export function writeMarker(rootAbs, marker, opts = {}) {
  const markerPath = markerPathFor(rootAbs);
  const text = markerText(marker);

  const exists = fs.existsSync(markerPath);
  if (exists && opts.replace !== true) {
    const p = problem(
      MARKER_REFUSAL.ALREADY_PRESENT,
      '',
      `a marker already exists at ${markerPath}; registering a marked root would mint a ` +
        'second identity for it. Use steward reconcile --moved, or the explicit --claim ' +
        'route, rather than overwriting an existing identity claim',
    );
    const err = new Error(p.text);
    err.code = p.code;
    err.status = p.status;
    err.failure_row = p.failure_row;
    throw err;
  }

  fs.mkdirSync(path.dirname(markerPath), { recursive: true });
  // The bytes leave through the existing durable-write primitive: temp + fsync + rename,
  // in the marker's own directory. The marker is a per-project file, not the index log,
  // so this is the atomic-write path and never the D-1 append path.
  writeFileAtomicSync(markerPath, text);

  return {
    path: markerPath,
    hash: markerHash(text),
    bytes_len: Buffer.byteLength(text, 'utf8'),
    replaced: exists,
  };
}

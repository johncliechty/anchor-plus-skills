/**
 * W4 - commit-intent-v1, frozen before anything emits one.
 *
 * WHY THIS FILE EXISTS, AND WHY NOW. The consumer of this schema is not in this repo. The
 * engine never shells to git; it emits an intent, and Anchor (a separate effort, a
 * separate release) honors it. A schema with a consumer you cannot deploy in lockstep is
 * a schema you cannot change: the day W7 writes the first intent, the shape is load-bearing
 * across two repositories. That is the whole reason it is frozen in W4 rather than in the
 * wave that first emits it.
 *
 * WHAT AN INTENT SAYS, precisely: "these exact bytes, at these paths, inside this project,
 * were made durable by the engine for this reason, and this is the Nth such statement
 * about this project". It is a REQUEST, not a report. 'receipt written' and 'receipt
 * honored' are different facts (W15), and nothing here claims the second: an intent
 * carries no commit id and no acknowledgement, because the engine has no way to know one.
 *
 * THREE FIELDS DO REAL WORK.
 *
 *  - `seq` is PER-PROJECT and monotonic with no gaps. It is what makes a missing
 *    acknowledgement detectable: a hole in the run means an intent was written and lost,
 *    which is exactly the fact the durability banner exists to surface. A gap is refused
 *    here rather than tolerated, because a tolerated gap cannot later be distinguished
 *    from a lost intent.
 *
 *  - the per-path `sha256` + `byte_len` pair is W14's tamper baseline. Detection strength
 *    equals the last acknowledged intent, which is stated honestly in the disaster tree
 *    rather than implied to be more.
 *
 *  - `path` is ROOT-RELATIVE with POSIX separators, and a path that escapes its root is
 *    refused as TAMPERED. An absolute path in an intent would name a location on one
 *    machine; a `..` segment would name a file outside the project the intent claims to be
 *    about. Both are refused at construction, so a bad path cannot reach the log.
 *
 * `written_at` is a wall clock and is REPORTING ONLY (NG-4): it never orders, compares or
 * dedupes anything. The log's own sequence is the sole total order.
 *
 * Stdlib only.
 */

import crypto from 'node:crypto';

import { PROJECT_ID_PATTERN } from './marker.mjs';
import { INTEGRITY, assertStatusCode } from './status.mjs';

/** The frozen schema id, carried in every intent. */
export const COMMIT_INTENT_SCHEMA = 'commit-intent-v1';

/** Top-level field order. Also the JSON.stringify replacer, so bytes cannot drift. */
export const COMMIT_INTENT_FIELDS = Object.freeze([
  'schema',
  'project_id',
  'seq',
  'reason',
  'paths',
  'path',
  'sha256',
  'byte_len',
  'written_at',
]);

/** The fields of one entry in `paths`. */
export const PATH_ENTRY_FIELDS = Object.freeze(['path', 'sha256', 'byte_len']);

/**
 * The closed reason set. A reason is why the engine wants these bytes committed, and it
 * is closed so the Anchor side can switch on it exhaustively rather than string-matching.
 */
export const COMMIT_REASON = Object.freeze({
  REGISTER: 'REGISTER',
  RECEIPT_WRITTEN: 'RECEIPT_WRITTEN',
  INSTRUMENT_WRITTEN: 'INSTRUMENT_WRITTEN',
  ROADMAP_EVENT_WRITTEN: 'ROADMAP_EVENT_WRITTEN',
  RECONCILE: 'RECONCILE',
  COMPACT: 'COMPACT',
  BUNDLE_EXPORT: 'BUNDLE_EXPORT',
  RECOVER_LOG: 'RECOVER_LOG',
});

/** @type {ReadonlyArray<string>} */
export const COMMIT_REASONS = Object.freeze(Object.values(COMMIT_REASON));

/** The refusals this module raises. */
export const COMMIT_INTENT_REFUSAL = Object.freeze({
  NOT_AN_OBJECT: 'COMMIT_INTENT_NOT_AN_OBJECT',
  SCHEMA_MISMATCH: 'COMMIT_INTENT_SCHEMA_MISMATCH',
  UNKNOWN_FIELD: 'COMMIT_INTENT_UNKNOWN_FIELD',
  FIELD_MISSING: 'COMMIT_INTENT_FIELD_MISSING',
  PROJECT_ID_MALFORMED: 'COMMIT_INTENT_PROJECT_ID_MALFORMED',
  REASON_UNKNOWN: 'COMMIT_INTENT_REASON_UNKNOWN',
  SEQ_MALFORMED: 'COMMIT_INTENT_SEQ_MALFORMED',
  SEQ_REGRESSION: 'COMMIT_INTENT_SEQ_REGRESSION',
  SEQ_GAP: 'COMMIT_INTENT_SEQ_GAP',
  PATHS_EMPTY: 'COMMIT_INTENT_PATHS_EMPTY',
  PATHS_UNSORTED: 'COMMIT_INTENT_PATHS_UNSORTED',
  PATH_DUPLICATE: 'COMMIT_INTENT_PATH_DUPLICATE',
  PATH_NOT_RELATIVE: 'COMMIT_INTENT_PATH_NOT_RELATIVE',
  PATH_ESCAPES_ROOT: 'COMMIT_INTENT_PATH_ESCAPES_ROOT',
  PATH_SEPARATOR: 'COMMIT_INTENT_PATH_SEPARATOR',
  HASH_MALFORMED: 'COMMIT_INTENT_HASH_MALFORMED',
  BYTE_LEN_MALFORMED: 'COMMIT_INTENT_BYTE_LEN_MALFORMED',
  TIMESTAMP_MALFORMED: 'COMMIT_INTENT_TIMESTAMP_MALFORMED',
});

/** refusal -> STATUS-v1 code. Containment failures are TAMPERED; the rest are schema. */
export const COMMIT_INTENT_STATUS = Object.freeze({
  [COMMIT_INTENT_REFUSAL.PATH_ESCAPES_ROOT]: INTEGRITY.TAMPERED,
  [COMMIT_INTENT_REFUSAL.PATH_NOT_RELATIVE]: INTEGRITY.TAMPERED,
});

/** The frozen W3 row a containment refusal renders through. */
export const COMMIT_INTENT_FAILURE_ROW = 'REBUILD_PATH_ESCAPE';

/** 64 lowercase hex characters. One spelling per hash, forever. */
export const SHA256_PATTERN = /^[0-9a-f]{64}$/;

/** ISO-8601 UTC. Recorded, never compared. */
export const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;

/** @param {string} code @param {string} field @param {string} detail @returns {object} */
function problem(code, field, detail) {
  const status = COMMIT_INTENT_STATUS[code] ?? INTEGRITY.UNPARSEABLE;
  return Object.freeze({
    code,
    field,
    detail,
    status: assertStatusCode(status, `commit-intent refusal ${code}`),
    failure_row: COMMIT_INTENT_STATUS[code] === INTEGRITY.TAMPERED ? COMMIT_INTENT_FAILURE_ROW : null,
    text: `${code}: ${detail}`,
  });
}

/** @param {Buffer|string} bytes @returns {string} sha256 hex of the exact bytes */
export function hashBytes(bytes) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

/**
 * One entry of `paths`, built from the bytes that were actually written.
 *
 * @param {string} rootRelPath POSIX, relative to the project root
 * @param {Buffer|string} bytes
 * @returns {{path: string, sha256: string, byte_len: number}}
 */
export function pathEntryFor(rootRelPath, bytes) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
  return Object.freeze({
    path: String(rootRelPath),
    sha256: hashBytes(buffer),
    byte_len: buffer.length,
  });
}

/**
 * Is this a safe root-relative path?
 *
 * @param {string} p @returns {string|null} the refusal code, or null when the path is fine
 */
export function pathRefusalFor(p) {
  if (typeof p !== 'string' || p.trim() === '') return COMMIT_INTENT_REFUSAL.PATH_NOT_RELATIVE;
  if (p.includes('\\')) return COMMIT_INTENT_REFUSAL.PATH_SEPARATOR;
  if (p.startsWith('/')) return COMMIT_INTENT_REFUSAL.PATH_NOT_RELATIVE;
  if (/^[A-Za-z]:/.test(p)) return COMMIT_INTENT_REFUSAL.PATH_NOT_RELATIVE;
  const segments = p.split('/');
  if (segments.includes('..')) return COMMIT_INTENT_REFUSAL.PATH_ESCAPES_ROOT;
  if (segments.some((s) => s === '')) return COMMIT_INTENT_REFUSAL.PATH_NOT_RELATIVE;
  return null;
}

/**
 * Validate a candidate commit-intent. Reports every problem, in field order.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, intent: object|null, problems: Array<object>}}
 */
export function validateCommitIntent(value) {
  const problems = [];

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.NOT_AN_OBJECT,
      '',
      `a ${COMMIT_INTENT_SCHEMA} is a JSON object; got ${Array.isArray(value) ? 'an array' : typeof value}`,
    ));
    return { ok: false, intent: null, problems: Object.freeze(problems) };
  }

  const record = /** @type {Record<string, unknown>} */ (value);
  const topLevel = ['schema', 'project_id', 'seq', 'reason', 'paths', 'written_at'];

  for (const key of Object.keys(record)) {
    if (!topLevel.includes(key)) {
      problems.push(problem(
        COMMIT_INTENT_REFUSAL.UNKNOWN_FIELD,
        key,
        `${COMMIT_INTENT_SCHEMA} is frozen across two repositories and carries no '${key}'`,
      ));
    }
  }
  for (const key of topLevel) {
    if (!Object.prototype.hasOwnProperty.call(record, key) || record[key] === undefined) {
      problems.push(problem(COMMIT_INTENT_REFUSAL.FIELD_MISSING, key, `${key} is absent`));
    }
  }

  if (record.schema !== undefined && record.schema !== COMMIT_INTENT_SCHEMA) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.SCHEMA_MISMATCH,
      'schema',
      `expected ${COMMIT_INTENT_SCHEMA}, got ${JSON.stringify(record.schema)}`,
    ));
  }

  if (record.project_id !== undefined && !PROJECT_ID_PATTERN.test(String(record.project_id))) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.PROJECT_ID_MALFORMED,
      'project_id',
      `${JSON.stringify(record.project_id)} is not a minted identifier`,
    ));
  }

  if (record.seq !== undefined
    && (!Number.isInteger(record.seq) || /** @type {number} */ (record.seq) < 1)) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.SEQ_MALFORMED,
      'seq',
      `${JSON.stringify(record.seq)} is not a positive integer; seq is per-project and starts at 1`,
    ));
  }

  if (record.reason !== undefined && !COMMIT_REASONS.includes(/** @type {string} */ (record.reason))) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.REASON_UNKNOWN,
      'reason',
      `${JSON.stringify(record.reason)} is not one of ${COMMIT_REASONS.join(', ')}`,
    ));
  }

  if (record.paths !== undefined) {
    if (!Array.isArray(record.paths) || record.paths.length === 0) {
      problems.push(problem(
        COMMIT_INTENT_REFUSAL.PATHS_EMPTY,
        'paths',
        'an intent with no paths asks for nothing to be committed and would be indistinguishable ' +
          'from a lost intent',
      ));
    } else {
      const seen = new Set();
      let previous = null;
      record.paths.forEach((entry, i) => {
        const label = `paths[${i}]`;
        if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
          problems.push(problem(COMMIT_INTENT_REFUSAL.NOT_AN_OBJECT, label, 'a path entry is an object'));
          return;
        }
        const item = /** @type {Record<string, unknown>} */ (entry);
        for (const key of Object.keys(item)) {
          if (!PATH_ENTRY_FIELDS.includes(key)) {
            problems.push(problem(COMMIT_INTENT_REFUSAL.UNKNOWN_FIELD, `${label}.${key}`, 'not a path-entry field'));
          }
        }
        for (const key of PATH_ENTRY_FIELDS) {
          if (item[key] === undefined) {
            problems.push(problem(COMMIT_INTENT_REFUSAL.FIELD_MISSING, `${label}.${key}`, `${key} is absent`));
          }
        }

        const p = item.path;
        const refusal = pathRefusalFor(/** @type {string} */ (p));
        if (refusal !== null) {
          problems.push(problem(
            refusal,
            `${label}.path`,
            `${JSON.stringify(p)} must be a root-relative POSIX path inside the project; an ` +
              'absolute path names one machine and a parent segment names a file the intent ' +
              'has no authority over',
          ));
        } else {
          const key = String(p).toLowerCase();
          if (seen.has(key)) {
            problems.push(problem(COMMIT_INTENT_REFUSAL.PATH_DUPLICATE, `${label}.path`, `${p} appears twice`));
          }
          seen.add(key);
          if (previous !== null && String(p) < previous) {
            problems.push(problem(
              COMMIT_INTENT_REFUSAL.PATHS_UNSORTED,
              `${label}.path`,
              `${p} sorts before ${previous}; paths are ordered so the same set of files always ` +
                'produces the same intent bytes',
            ));
          }
          previous = String(p);
        }

        if (item.sha256 !== undefined && !SHA256_PATTERN.test(String(item.sha256))) {
          problems.push(problem(
            COMMIT_INTENT_REFUSAL.HASH_MALFORMED,
            `${label}.sha256`,
            `${JSON.stringify(item.sha256)} is not 64 lowercase hex characters`,
          ));
        }
        if (item.byte_len !== undefined
          && (!Number.isInteger(item.byte_len) || /** @type {number} */ (item.byte_len) < 0)) {
          problems.push(problem(
            COMMIT_INTENT_REFUSAL.BYTE_LEN_MALFORMED,
            `${label}.byte_len`,
            `${JSON.stringify(item.byte_len)} is not a non-negative integer`,
          ));
        }
      });
    }
  }

  if (record.written_at !== undefined
    && (!TIMESTAMP_PATTERN.test(String(record.written_at)) || Number.isNaN(Date.parse(String(record.written_at))))) {
    problems.push(problem(
      COMMIT_INTENT_REFUSAL.TIMESTAMP_MALFORMED,
      'written_at',
      `${JSON.stringify(record.written_at)} is not an ISO-8601 UTC instant. It is a record for ` +
        'the operator to read and never an ordering key',
    ));
  }

  if (problems.length > 0) return { ok: false, intent: null, problems: Object.freeze(problems) };

  const intent = Object.freeze({
    schema: COMMIT_INTENT_SCHEMA,
    project_id: String(record.project_id),
    seq: Number(record.seq),
    reason: String(record.reason),
    paths: Object.freeze(/** @type {Array<any>} */ (record.paths).map((e) => Object.freeze({
      path: String(e.path),
      sha256: String(e.sha256),
      byte_len: Number(e.byte_len),
    }))),
    written_at: String(record.written_at),
  });

  return { ok: true, intent, problems: Object.freeze([]) };
}

/**
 * Build an intent, sorting its paths and validating on the way out. There is no route from
 * an invalid intent to the log.
 *
 * @param {{project_id: string, seq: number, reason: string,
 *          paths: Array<{path: string, sha256: string, byte_len: number}>,
 *          written_at: string}} parts
 * @returns {object} the frozen intent
 */
export function makeCommitIntent(parts) {
  const input = parts ?? {};
  const paths = Array.isArray(input.paths)
    ? input.paths
      .map((e) => (e && typeof e === 'object' && !Array.isArray(e)
        ? { path: e.path, sha256: e.sha256, byte_len: e.byte_len }
        : e))
      .sort((a, b) => {
        const pa = a && typeof a.path === 'string' ? a.path : '';
        const pb = b && typeof b.path === 'string' ? b.path : '';
        return pa < pb ? -1 : pa > pb ? 1 : 0;
      })
    : input.paths;

  const candidate = {
    schema: COMMIT_INTENT_SCHEMA,
    project_id: input.project_id,
    seq: input.seq,
    reason: input.reason,
    paths,
    written_at: input.written_at,
  };
  const result = validateCommitIntent(candidate);
  if (!result.ok) {
    throw new Error(`${COMMIT_INTENT_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return result.intent;
}

/**
 * The intent's canonical bytes: declared key order, no whitespace, one LF-terminated line
 * - the shape the D-1 append primitive writes.
 *
 * @param {object} intent @returns {string}
 */
export function commitIntentLine(intent) {
  const result = validateCommitIntent(intent);
  if (!result.ok) {
    throw new Error(`${COMMIT_INTENT_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return `${JSON.stringify(result.intent, COMMIT_INTENT_FIELDS.slice())}\n`;
}

/** @param {object} intent @returns {string} sha256 of the canonical line */
export function commitIntentHash(intent) {
  return hashBytes(commitIntentLine(intent));
}

/**
 * The next per-project sequence. Separate from the log's global sequence on purpose: one
 * project's intents must be countable without reading another project's events.
 *
 * @param {number|null} previousSeq @returns {number}
 */
export function nextSeqFor(previousSeq) {
  if (previousSeq === null || previousSeq === undefined) return 1;
  if (!Number.isInteger(previousSeq) || previousSeq < 0) {
    throw new Error(`${COMMIT_INTENT_REFUSAL.SEQ_MALFORMED}: ${JSON.stringify(previousSeq)}`);
  }
  return previousSeq + 1;
}

/**
 * Refuse a sequence that regresses OR skips.
 *
 * A gap is refused rather than tolerated because a tolerated gap can never afterwards be
 * told apart from an intent that was written and lost - and telling those apart is the
 * entire purpose of the per-project run.
 *
 * @param {number|null} previousSeq @param {number} nextSeq @returns {number} nextSeq
 */
export function assertSeqMonotonic(previousSeq, nextSeq) {
  const expected = nextSeqFor(previousSeq);
  if (!Number.isInteger(nextSeq) || nextSeq < 1) {
    throw new Error(`${COMMIT_INTENT_REFUSAL.SEQ_MALFORMED}: ${JSON.stringify(nextSeq)} is not a positive integer`);
  }
  if (nextSeq <= (previousSeq ?? 0)) {
    throw new Error(
      `${COMMIT_INTENT_REFUSAL.SEQ_REGRESSION}: seq ${nextSeq} does not follow ${previousSeq}; ` +
        'a per-project intent sequence never goes backwards',
    );
  }
  if (nextSeq !== expected) {
    throw new Error(
      `${COMMIT_INTENT_REFUSAL.SEQ_GAP}: expected seq ${expected} after ${previousSeq}, got ${nextSeq}; ` +
        'a gap and a lost intent are indistinguishable after the fact, so the gap is refused now',
    );
  }
  return nextSeq;
}

/**
 * The highest sequence recorded for a project in a set of intents.
 *
 * @param {Array<{project_id: string, seq: number}>} intents @param {string} projectId
 * @returns {number|null}
 */
export function highestSeqFor(intents, projectId) {
  let highest = null;
  for (const intent of intents ?? []) {
    if (!intent || intent.project_id !== projectId) continue;
    if (highest === null || intent.seq > highest) highest = intent.seq;
  }
  return highest;
}

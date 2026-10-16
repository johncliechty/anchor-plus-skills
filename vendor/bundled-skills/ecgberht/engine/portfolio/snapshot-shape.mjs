/**
 * W4 - the D-2 snapshot shape, with the freshness block frozen CLOSED.
 *
 * WHY THIS FILE EXISTS. C1 says a deleted snapshot rebuilds byte-equal. A byte-equality
 * claim dies the moment one nondeterministic field is admitted anywhere in the artifact -
 * and something always has to be nondeterministic, because "when did we last see this
 * project" is a real question an operator asks. D-2 resolves that by splitting the
 * artifact rather than weakening the claim: `body` is the canonical, clock-free,
 * host-free region compared byte for byte, and `freshness` is ONE named block, with a
 * CLOSED field set, that is allowed to vary.
 *
 * THE BLOCK IS A FENCE, NOT AN ESCAPE HATCH. The failure mode this validator exists to
 * prevent is entirely predictable: some later wave needs to stash a value that will not
 * survive a rebuild, notices that `freshness` is "the place where varying things go", and
 * puts it there. Two waves later the freshness block is a junk drawer, and W6's purity
 * test - which asserts `body` is byte-identical and `freshness` "contains only the frozen
 * fields" - is passing over a field set that has quietly grown. So the field set is a
 * closed enumeration and an unknown key is refused BY NAME, at every level: the block, and
 * each per-project entry inside it.
 *
 * WHAT THE FIELDS MEAN, so nobody has to guess and add a synonym:
 *   head_seq      the log sequence this snapshot was computed at. The tail merge (D-3)
 *                 replays events after it; the cap on that tail is caps.tail_events.
 *   head_sha256   the hash of the log head at that sequence - what makes a stale restore
 *                 detectable (W14) rather than merely suspected.
 *   computed_at   wall clock, for the operator to read. NG-4: it orders nothing.
 *   per_project   {last_seen, last_verified, presence, freshness} per project_id, and
 *                 nothing else. presence and freshness are STATUS-v1 codes, not free text.
 *
 * Stdlib only.
 */

import {
  FRESHNESS,
  INTEGRITY,
  PRESENCE,
  assertStatusCode,
  isOnAxis,
  AXIS,
} from './status.mjs';

/** The declared derived-schema id the snapshot carries (brief-cache-v0 pattern). */
export const SNAPSHOT_SCHEMA = 'portfolio-index-v0';

/** The three top-level keys. Closed. */
export const SNAPSHOT_KEYS = Object.freeze(['schema', 'body', 'freshness']);

/** The freshness block's CLOSED field set, in canonical order. */
export const FRESHNESS_KEYS = Object.freeze(['head_seq', 'head_sha256', 'computed_at', 'per_project']);

/** Each per-project freshness entry's CLOSED field set, in canonical order. */
export const PER_PROJECT_KEYS = Object.freeze(['last_seen', 'last_verified', 'presence', 'freshness']);

/** The refusals this module raises. */
export const SNAPSHOT_REFUSAL = Object.freeze({
  NOT_AN_OBJECT: 'SNAPSHOT_NOT_AN_OBJECT',
  SCHEMA_MISMATCH: 'SNAPSHOT_SCHEMA_MISMATCH',
  UNKNOWN_KEY: 'SNAPSHOT_UNKNOWN_KEY',
  KEY_MISSING: 'SNAPSHOT_KEY_MISSING',
  BODY_NOT_AN_OBJECT: 'SNAPSHOT_BODY_NOT_AN_OBJECT',
  FRESHNESS_NOT_AN_OBJECT: 'SNAPSHOT_FRESHNESS_NOT_AN_OBJECT',
  FRESHNESS_UNKNOWN_KEY: 'SNAPSHOT_FRESHNESS_UNKNOWN_KEY',
  FRESHNESS_KEY_MISSING: 'SNAPSHOT_FRESHNESS_KEY_MISSING',
  FRESHNESS_FIELD_MALFORMED: 'SNAPSHOT_FRESHNESS_FIELD_MALFORMED',
  PER_PROJECT_UNKNOWN_KEY: 'SNAPSHOT_PER_PROJECT_UNKNOWN_KEY',
  PER_PROJECT_KEY_MISSING: 'SNAPSHOT_PER_PROJECT_KEY_MISSING',
  PER_PROJECT_FIELD_MALFORMED: 'SNAPSHOT_PER_PROJECT_FIELD_MALFORMED',
});

/** ISO-8601 UTC. The only clock in the artifact, and it lives here by construction. */
export const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;

/** 64 lowercase hex characters, or null for an empty log. */
export const SHA256_PATTERN = /^[0-9a-f]{64}$/;

/** @param {string} code @param {string} field @param {string} detail @returns {object} */
function problem(code, field, detail) {
  return Object.freeze({
    code,
    field,
    detail,
    status: assertStatusCode(INTEGRITY.UNPARSEABLE, `snapshot refusal ${code}`),
    text: `${code}: ${field ? `${field} - ` : ''}${detail}`,
  });
}

/** @param {unknown} v @returns {boolean} */
function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** @param {unknown} v @returns {boolean} an ISO instant or an explicit null */
function isInstantOrNull(v) {
  if (v === null) return true;
  return typeof v === 'string' && TIMESTAMP_PATTERN.test(v) && !Number.isNaN(Date.parse(v));
}

/**
 * Validate ONE per-project freshness entry.
 *
 * @param {string} projectId @param {unknown} value @returns {Array<object>} problems
 */
export function validatePerProjectFreshness(projectId, value) {
  const problems = [];
  const where = `freshness.per_project.${projectId}`;

  if (!isPlainObject(value)) {
    problems.push(problem(SNAPSHOT_REFUSAL.PER_PROJECT_FIELD_MALFORMED, where, 'not an object'));
    return problems;
  }
  const entry = /** @type {Record<string, unknown>} */ (value);

  for (const key of Object.keys(entry)) {
    if (!PER_PROJECT_KEYS.includes(key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.PER_PROJECT_UNKNOWN_KEY,
        `${where}.${key}`,
        `a per-project freshness entry carries exactly ${PER_PROJECT_KEYS.join(', ')}; ` +
          `'${key}' is outside the frozen set, and the block is a fence rather than a place ` +
          'to park a value that will not survive a rebuild',
      ));
    }
  }
  for (const key of PER_PROJECT_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(entry, key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.PER_PROJECT_KEY_MISSING,
        `${where}.${key}`,
        'required by the frozen per-project field set, and not carried by this entry',
      ));
    }
  }

  if (Object.prototype.hasOwnProperty.call(entry, 'last_seen') && !isInstantOrNull(entry.last_seen)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.PER_PROJECT_FIELD_MALFORMED,
      `${where}.last_seen`,
      'must be an ISO-8601 UTC instant or null (null means never seen, which is a fact, not a zero)',
    ));
  }
  if (Object.prototype.hasOwnProperty.call(entry, 'last_verified') && !isInstantOrNull(entry.last_verified)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.PER_PROJECT_FIELD_MALFORMED,
      `${where}.last_verified`,
      'must be an ISO-8601 UTC instant or null',
    ));
  }
  if (Object.prototype.hasOwnProperty.call(entry, 'presence') && !isOnAxis(entry.presence, AXIS.PRESENCE)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.PER_PROJECT_FIELD_MALFORMED,
      `${where}.presence`,
      `${JSON.stringify(entry.presence)} is not a STATUS-v1 presence code ` +
        `(${Object.values(PRESENCE).join(', ')})`,
    ));
  }
  if (Object.prototype.hasOwnProperty.call(entry, 'freshness') && !isOnAxis(entry.freshness, AXIS.FRESHNESS)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.PER_PROJECT_FIELD_MALFORMED,
      `${where}.freshness`,
      `${JSON.stringify(entry.freshness)} is not a STATUS-v1 freshness code ` +
        `(${Object.values(FRESHNESS).join(', ')})`,
    ));
  }

  return problems;
}

/**
 * Validate the freshness block on its own - the D-2 fence, checked in isolation so W6 can
 * assert it over a block it built without constructing a whole snapshot.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, problems: Array<object>}}
 */
export function validateFreshnessBlock(value) {
  const problems = [];

  if (!isPlainObject(value)) {
    problems.push(problem(SNAPSHOT_REFUSAL.FRESHNESS_NOT_AN_OBJECT, 'freshness', 'not an object'));
    return { ok: false, problems: Object.freeze(problems) };
  }
  const block = /** @type {Record<string, unknown>} */ (value);

  for (const key of Object.keys(block)) {
    if (!FRESHNESS_KEYS.includes(key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.FRESHNESS_UNKNOWN_KEY,
        `freshness.${key}`,
        `the freshness block carries exactly ${FRESHNESS_KEYS.join(', ')}. '${key}' is outside ` +
          'the frozen set: the block is the ONE region permitted to vary, which is precisely ' +
          'why it may not also be the region where anything at all may be stored',
      ));
    }
  }
  for (const key of FRESHNESS_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(block, key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.FRESHNESS_KEY_MISSING,
        `freshness.${key}`,
        'required by the frozen freshness field set, and not carried by this block',
      ));
    }
  }

  if (Object.prototype.hasOwnProperty.call(block, 'head_seq')
    && (!Number.isInteger(block.head_seq) || /** @type {number} */ (block.head_seq) < 0)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.FRESHNESS_FIELD_MALFORMED,
      'freshness.head_seq',
      `${JSON.stringify(block.head_seq)} is not a non-negative integer; it is the log sequence ` +
        'the tail merge replays from, so a wrong value silently hides events',
    ));
  }
  if (Object.prototype.hasOwnProperty.call(block, 'head_sha256')
    && !(block.head_sha256 === null || (typeof block.head_sha256 === 'string' && SHA256_PATTERN.test(block.head_sha256)))) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.FRESHNESS_FIELD_MALFORMED,
      'freshness.head_sha256',
      `${JSON.stringify(block.head_sha256)} is neither 64 lowercase hex characters nor null (an empty log)`,
    ));
  }
  if (Object.prototype.hasOwnProperty.call(block, 'computed_at') && !isInstantOrNull(block.computed_at)) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.FRESHNESS_FIELD_MALFORMED,
      'freshness.computed_at',
      'must be an ISO-8601 UTC instant; it is read by the operator and orders nothing',
    ));
  }
  if (Object.prototype.hasOwnProperty.call(block, 'per_project')) {
    if (!isPlainObject(block.per_project)) {
      problems.push(problem(SNAPSHOT_REFUSAL.FRESHNESS_FIELD_MALFORMED, 'freshness.per_project', 'not an object'));
    } else {
      for (const projectId of Object.keys(/** @type {object} */ (block.per_project))) {
        problems.push(...validatePerProjectFreshness(projectId, block.per_project[projectId]));
      }
    }
  }

  return { ok: problems.length === 0, problems: Object.freeze(problems) };
}

/**
 * Validate the whole snapshot shape.
 *
 * This checks the SHAPE, not the contents of `body`: body's canonical ordering and its
 * freedom from clocks and hostnames are W6's purity lint, which owns the serializer. What
 * is settled here is the split itself - three keys, and a closed freshness block - because
 * every later wave reads the artifact through this shape.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, problems: Array<object>}}
 */
export function validateSnapshotShape(value) {
  const problems = [];

  if (!isPlainObject(value)) {
    problems.push(problem(SNAPSHOT_REFUSAL.NOT_AN_OBJECT, '', 'a snapshot is a JSON object'));
    return { ok: false, problems: Object.freeze(problems) };
  }
  const snapshot = /** @type {Record<string, unknown>} */ (value);

  for (const key of Object.keys(snapshot)) {
    if (!SNAPSHOT_KEYS.includes(key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.UNKNOWN_KEY,
        key,
        `a snapshot carries exactly ${SNAPSHOT_KEYS.join(', ')}; a fourth top-level key would ` +
          'be a region neither the byte-equality claim nor the freshness fence covers',
      ));
    }
  }
  for (const key of SNAPSHOT_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(snapshot, key)) {
      problems.push(problem(
        SNAPSHOT_REFUSAL.KEY_MISSING,
        key,
        'required by the three-key snapshot shape, and not carried by this artifact',
      ));
    }
  }

  if (Object.prototype.hasOwnProperty.call(snapshot, 'schema') && snapshot.schema !== SNAPSHOT_SCHEMA) {
    problems.push(problem(
      SNAPSHOT_REFUSAL.SCHEMA_MISMATCH,
      'schema',
      `expected ${SNAPSHOT_SCHEMA}, got ${JSON.stringify(snapshot.schema)}; the id is what marks ` +
        'this artifact DERIVED and therefore safe to delete and rebuild',
    ));
  }

  if (Object.prototype.hasOwnProperty.call(snapshot, 'body') && !isPlainObject(snapshot.body)) {
    problems.push(problem(SNAPSHOT_REFUSAL.BODY_NOT_AN_OBJECT, 'body', 'not an object'));
  }

  if (Object.prototype.hasOwnProperty.call(snapshot, 'freshness')) {
    problems.push(...validateFreshnessBlock(snapshot.freshness).problems);
  }

  return { ok: problems.length === 0, problems: Object.freeze(problems) };
}

/**
 * A freshness block with every frozen field present and nothing else - the starting point
 * W5 and W6 build from, so no wave has to remember the field list.
 *
 * @param {{head_seq?: number, head_sha256?: string|null, computed_at?: string|null,
 *          per_project?: Record<string, object>}} [parts]
 * @returns {object}
 */
export function emptyFreshnessBlock(parts = {}) {
  return {
    head_seq: parts.head_seq ?? 0,
    head_sha256: parts.head_sha256 ?? null,
    computed_at: parts.computed_at ?? null,
    per_project: parts.per_project ?? {},
  };
}

/**
 * One per-project freshness entry with every frozen field present.
 *
 * @param {{last_seen?: string|null, last_verified?: string|null, presence?: string,
 *          freshness?: string}} [parts]
 * @returns {object}
 */
export function perProjectFreshness(parts = {}) {
  return {
    last_seen: parts.last_seen ?? null,
    last_verified: parts.last_verified ?? null,
    presence: parts.presence ?? PRESENCE.UNREACHABLE,
    freshness: parts.freshness ?? FRESHNESS.UNKNOWN,
  };
}

/**
 * @param {object} [parts]
 * @returns {{schema: string, body: object, freshness: object}}
 */
export function emptySnapshot(parts = {}) {
  return {
    schema: SNAPSHOT_SCHEMA,
    body: parts.body ?? {},
    freshness: parts.freshness ?? emptyFreshnessBlock(),
  };
}

/** @param {Array<object>} problems @returns {string} a message naming every offending key */
export function formatSnapshotProblems(problems) {
  if (!problems || problems.length === 0) return 'the snapshot shape is intact';
  return problems.map((p) => `  ${p.text}`).join('\n');
}

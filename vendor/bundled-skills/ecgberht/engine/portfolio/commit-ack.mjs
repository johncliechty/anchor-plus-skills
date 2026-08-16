/**
 * W15 - commit-ack-v1: the OTHER half of the Anchor contract.
 *
 * WHY IT IS A SEPARATE SCHEMA FROM commit-intent-v1. 'receipt written' and 'receipt
 * honored' are different facts, and the whole point of this wave is that the engine may
 * only ever state the first. An intent is a REQUEST this engine emits; an ack is a REPORT
 * some other process (Anchor) hands back, and the engine's job is to ACCEPT it - to
 * validate bytes it did not write, from a release it cannot deploy in lockstep with its
 * own. That is a parser, not a constructor, and parsers written as an afterthought inside
 * a producer end up trusting their own output shape.
 *
 * WHY IT IS A LEAF MODULE. registry.mjs must validate an ack to fold it into the view, and
 * the ack-latency health that reads the view lives one layer above. Putting the schema
 * here - beside commit-intent.mjs, importing nothing but the two vocabularies - is what
 * keeps that stack acyclic.
 *
 * THE FOUR FIELDS THAT DO WORK.
 *
 *  - `intent_seq` is the PER-PROJECT intent sequence being acknowledged, not a log seq. It
 *    is what turns a pile of acks into a watermark: everything at or below the highest
 *    acknowledged intent has left this machine.
 *
 *  - `intent_sha256` binds the ack to the exact bytes of the intent line. Without it an ack
 *    says "I committed number 4" and nobody can tell WHICH number 4 - the one this log
 *    holds, or the one a restored-from-backup log held. With it, an ack that does not match
 *    the local lineage is detectable rather than silently believed.
 *
 *  - `commit_id` is OPAQUE. The engine never parses it, never orders by it, and never
 *    resolves it against anything: it is the durability layer's own name for what it did,
 *    carried so an operator can hand it to that layer. Treating it as structured would be
 *    the engine knowing about the durability layer's internals, which is the coupling this
 *    whole contract exists to avoid.
 *
 *  - `anchor` names WHO acknowledged. An ack with no author cannot be revoked, audited, or
 *    told apart from one a test fixture left behind.
 *
 * `acked_at` is a wall clock and is REPORTING ONLY (NG-4). It is what the escalation ladder
 * reads to say "N days", and it never orders, compares or dedupes an event: the log's own
 * sequence is the sole total order, here as everywhere.
 *
 * Stdlib only.
 */

import { SHA256_PATTERN, TIMESTAMP_PATTERN, hashBytes } from './commit-intent.mjs';
import { PROJECT_ID_PATTERN } from './marker.mjs';
import { INTEGRITY, assertStatusCode } from './status.mjs';

/** The frozen schema id, carried in every ack. */
export const COMMIT_ACK_SCHEMA = 'commit-ack-v1';

/** Top-level field order. Also the JSON.stringify replacer, so bytes cannot drift. */
export const COMMIT_ACK_FIELDS = Object.freeze([
  'schema',
  'project_id',
  'intent_seq',
  'intent_sha256',
  'commit_id',
  'anchor',
  'acked_at',
]);

/**
 * The durability layer's own name for what it committed. Bounded and printable, and
 * deliberately NOT hex-shaped: the engine does not know what a commit id looks like over
 * there, and a pattern that assumed would refuse a perfectly good ack from the next version.
 */
export const COMMIT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,127}$/;

/** Who acknowledged. Same bound, same reason. */
export const ANCHOR_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/+ -]{0,127}$/;

/** The refusals this module raises. */
export const COMMIT_ACK_REFUSAL = Object.freeze({
  NOT_AN_OBJECT: 'COMMIT_ACK_NOT_AN_OBJECT',
  SCHEMA_MISMATCH: 'COMMIT_ACK_SCHEMA_MISMATCH',
  UNKNOWN_FIELD: 'COMMIT_ACK_UNKNOWN_FIELD',
  FIELD_MISSING: 'COMMIT_ACK_FIELD_MISSING',
  PROJECT_ID_MALFORMED: 'COMMIT_ACK_PROJECT_ID_MALFORMED',
  INTENT_SEQ_MALFORMED: 'COMMIT_ACK_INTENT_SEQ_MALFORMED',
  INTENT_HASH_MALFORMED: 'COMMIT_ACK_INTENT_HASH_MALFORMED',
  COMMIT_ID_MALFORMED: 'COMMIT_ACK_COMMIT_ID_MALFORMED',
  ANCHOR_MALFORMED: 'COMMIT_ACK_ANCHOR_MALFORMED',
  TIMESTAMP_MALFORMED: 'COMMIT_ACK_TIMESTAMP_MALFORMED',
});

/**
 * An ack that does not match the local lineage. Kept separate from the schema refusals
 * above because it is a different KIND of problem: the bytes are well-formed and the
 * disagreement is about history, which is a fact for the operator rather than a bug in the
 * acknowledging process.
 */
export const ACK_MISMATCH = Object.freeze({
  NO_SUCH_INTENT: 'COMMIT_ACK_NO_SUCH_INTENT',
  HASH_DISAGREES: 'COMMIT_ACK_HASH_DISAGREES',
});

/** @param {string} code @param {string} field @param {string} detail @returns {object} */
function problem(code, field, detail) {
  return Object.freeze({
    code,
    field,
    detail,
    status: assertStatusCode(INTEGRITY.UNPARSEABLE, `commit-ack refusal ${code}`),
    text: `${code}: ${detail}`,
  });
}

/**
 * Validate a candidate ack. Reports every problem, in field order, for the same reason the
 * intent validator does: an operator repairing a hand-written ack should learn everything
 * wrong with it in one pass.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, ack: object|null, problems: Array<object>}}
 */
export function validateCommitAck(value) {
  const problems = [];

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.NOT_AN_OBJECT,
      '',
      `a ${COMMIT_ACK_SCHEMA} is a JSON object; got ${Array.isArray(value) ? 'an array' : typeof value}`,
    ));
    return { ok: false, ack: null, problems: Object.freeze(problems) };
  }

  const record = /** @type {Record<string, unknown>} */ (value);

  for (const key of Object.keys(record)) {
    if (!COMMIT_ACK_FIELDS.includes(key)) {
      problems.push(problem(
        COMMIT_ACK_REFUSAL.UNKNOWN_FIELD,
        key,
        `${COMMIT_ACK_SCHEMA} is frozen across two repositories and carries no '${key}'`,
      ));
    }
  }
  for (const key of COMMIT_ACK_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, key) || record[key] === undefined) {
      problems.push(problem(COMMIT_ACK_REFUSAL.FIELD_MISSING, key, `${key} is absent`));
    }
  }

  if (record.schema !== undefined && record.schema !== COMMIT_ACK_SCHEMA) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.SCHEMA_MISMATCH,
      'schema',
      `expected ${COMMIT_ACK_SCHEMA}, got ${JSON.stringify(record.schema)}`,
    ));
  }

  if (record.project_id !== undefined && !PROJECT_ID_PATTERN.test(String(record.project_id))) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.PROJECT_ID_MALFORMED,
      'project_id',
      `${JSON.stringify(record.project_id)} is not a minted identifier; an ack names the project `
        + 'whose intent it honours, and that id came from this engine in the intent itself',
    ));
  }

  if (record.intent_seq !== undefined
    && (!Number.isInteger(record.intent_seq) || /** @type {number} */ (record.intent_seq) < 1)) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.INTENT_SEQ_MALFORMED,
      'intent_seq',
      `${JSON.stringify(record.intent_seq)} is not a positive integer. It is the PER-PROJECT `
        + "intent sequence being acknowledged, never the log's own seq",
    ));
  }

  if (record.intent_sha256 !== undefined && !SHA256_PATTERN.test(String(record.intent_sha256))) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.INTENT_HASH_MALFORMED,
      'intent_sha256',
      `${JSON.stringify(record.intent_sha256)} is not 64 lowercase hex characters. Without the `
        + 'hash an ack cannot say WHICH intent number it honoured',
    ));
  }

  if (record.commit_id !== undefined && !COMMIT_ID_PATTERN.test(String(record.commit_id))) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.COMMIT_ID_MALFORMED,
      'commit_id',
      `${JSON.stringify(record.commit_id)} is not a bounded printable identifier. The engine `
        + 'never parses this value; it carries it so the operator can hand it back to the '
        + 'durability layer that issued it',
    ));
  }

  if (record.anchor !== undefined && !ANCHOR_ID_PATTERN.test(String(record.anchor))) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.ANCHOR_MALFORMED,
      'anchor',
      `${JSON.stringify(record.anchor)} does not name who acknowledged. An unattributed ack `
        + 'cannot be audited or revoked',
    ));
  }

  if (record.acked_at !== undefined
    && (!TIMESTAMP_PATTERN.test(String(record.acked_at))
      || Number.isNaN(Date.parse(String(record.acked_at))))) {
    problems.push(problem(
      COMMIT_ACK_REFUSAL.TIMESTAMP_MALFORMED,
      'acked_at',
      `${JSON.stringify(record.acked_at)} is not an ISO-8601 UTC instant. It is what the `
        + 'escalation ladder reads to say how many days, and it is never an ordering key',
    ));
  }

  if (problems.length > 0) return { ok: false, ack: null, problems: Object.freeze(problems) };

  const ack = Object.freeze({
    schema: COMMIT_ACK_SCHEMA,
    project_id: String(record.project_id),
    intent_seq: Number(record.intent_seq),
    intent_sha256: String(record.intent_sha256),
    commit_id: String(record.commit_id),
    anchor: String(record.anchor),
    acked_at: String(record.acked_at),
  });

  return { ok: true, ack, problems: Object.freeze([]) };
}

/**
 * Build an ack, validating on the way out. Used by the engine's own fixtures and by any
 * caller ingesting an ack that arrived as loose fields rather than as a document.
 *
 * @param {{project_id: string, intent_seq: number, intent_sha256: string, commit_id: string,
 *          anchor: string, acked_at: string}} parts
 * @returns {object} the frozen ack
 */
export function makeCommitAck(parts) {
  const input = parts ?? {};
  const result = validateCommitAck({
    schema: COMMIT_ACK_SCHEMA,
    project_id: input.project_id,
    intent_seq: input.intent_seq,
    intent_sha256: input.intent_sha256,
    commit_id: input.commit_id,
    anchor: input.anchor,
    acked_at: input.acked_at,
  });
  if (!result.ok) {
    throw new Error(`${COMMIT_ACK_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return result.ack;
}

/**
 * The ack's canonical bytes: declared key order, no whitespace, one LF-terminated line.
 *
 * @param {object} ack @returns {string}
 */
export function commitAckLine(ack) {
  const result = validateCommitAck(ack);
  if (!result.ok) {
    throw new Error(`${COMMIT_ACK_SCHEMA} refused: ${result.problems.map((p) => p.text).join('; ')}`);
  }
  return `${JSON.stringify(result.ack, COMMIT_ACK_FIELDS.slice())}\n`;
}

/** @param {object} ack @returns {string} sha256 of the canonical line */
export function commitAckHash(ack) {
  return hashBytes(commitAckLine(ack));
}

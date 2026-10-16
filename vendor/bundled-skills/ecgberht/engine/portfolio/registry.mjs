/**
 * W7 - registry.mjs: membership as a VIEW over NATIVE log events, and NOT a second store.
 *
 * WHY THIS FILE EXISTS, AND WHY IT HOLDS NOTHING. The One-Store resolution says there is
 * exactly ONE portfolio store: the append-only log, plus a snapshot that is wholly derived
 * from it. "Which projects are members" is the most tempting thing in the whole system to
 * keep somewhere convenient - a registry.json, a projects[] array maintained in place, a
 * map cached beside the snapshot. Every one of those is a SECOND store, and a second store
 * is not a performance decision, it is a correctness decision made by accident: the moment
 * membership lives in two places, one of them can be older than the other, and no code path
 * exists that can tell you which. Delete-and-rebuild then stops being a property of the
 * system and becomes a property of whichever copy happened to survive.
 *
 * So this module holds no state at all. It is a pure function from EVENTS to a view, plus a
 * thin reader that gets those events from the ONE log. It imports no node:fs - not as a
 * discipline but as a fact a test can check - so it could not write a store even by
 * accident, and it never reads the snapshot: the snapshot is derived from the same events
 * this module replays, so consulting it would be asking the same question twice and
 * believing the answer that happened to be handy.
 *
 * MEMBERSHIP IS NATIVE. A registration event is not a derived row and never replayable
 * from a project root - it is the ONLY record that a project_id was ever minted, which is
 * exactly why the live log is not in the deletable set (W17). Deleting the snapshot costs
 * nothing; deleting the log loses membership, and the marker-v2 in each root is the
 * git-free mirror that makes even that recoverable.
 *
 * THE VIEW IS ORDERED BY seq AND NOTHING ELSE (NG-4). Two registrations whose wall clocks
 * disagree - a DST step, an NTP correction, a VM resumed from a snapshot - materialize in
 * the order they were appended, because that order was decided under the lock and written
 * into the bytes. `registered_at` is carried for the operator to read and is used to order
 * nothing.
 *
 * DAMAGE IS REPORTED, NEVER THROWN AWAY AND NEVER THROWN. The log is append-only, so a
 * malformed NATIVE event cannot be edited out; it can only be classified. An event this
 * module cannot use lands in `ignored` with its seq and a reason, and an event that
 * contradicts an earlier one (one project_id registered twice, one root registered under
 * two ids) lands in `conflicts` with BOTH sides named - it binds neither and it counts each
 * project exactly once, which is the same rule identity.mjs applies to a cloned root.
 *
 * Stdlib only.
 */

import path from 'node:path';

import {
  ORDERING_FIELD,
  WALL_CLOCK_FIELD,
  openIndexForRead,
  replayEvents,
} from '../append-log.mjs';
import { COMMIT_ACK_SCHEMA, validateCommitAck } from './commit-ack.mjs';
import { COMMIT_INTENT_SCHEMA, SHA256_PATTERN, validateCommitIntent } from './commit-intent.mjs';
import { pathKey, samePath } from './identity.mjs';
import { PROJECT_ID_PATTERN, TIMESTAMP_PATTERN } from './marker.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The view's frozen version. It describes a RENDERING, not a file: nothing on disk is v1. */
export const REGISTRY_VERSION = 'registry-view-v1';

/** The NATIVE event version this module writes and reads. */
export const NATIVE_EVENT_VERSION = 1;

/** The field carrying an event's type, matching the derived-row shape W9 freezes. */
export const EVENT_TYPE_FIELD = 't';

/** The field carrying an event payload's own version. */
export const EVENT_VERSION_FIELD = 'v';

/**
 * The NATIVE event vocabulary. Closed: a type outside this set is not a membership fact,
 * and the materializer passes it by rather than guessing what it meant.
 */
export const NATIVE_EVENT = Object.freeze({
  REGISTRATION: 'registration',
  RECONCILE: 'reconcile',
  COMMIT_INTENT: 'commit-intent',
  // W15. The ack is NATIVE for the same reason membership is: it is a fact nothing else
  // records. A DERIVED row can be rebuilt from the roots; an acknowledgement that some
  // other process made these bytes durable off this box exists nowhere but here, so
  // anywhere other than the never-deletable log would be somewhere it can be lost.
  COMMIT_ACK: 'commit-ack',
  // W16. An export is NATIVE for the same reason an ack is: it is the record that a copy of
  // this store left the box, and nothing else in the system holds it. A DERIVED row can be
  // rebuilt from the roots and a snapshot can be recomputed from the log, but "a bundle of
  // this log existed at head N on this date" is unrecoverable from anywhere else - and it is
  // exactly the fact the degradation banner needs in order to say how old the off-box copy
  // is, rather than saying nothing and letting silence read as safety.
  BUNDLE_EXPORTED: 'bundle-exported',
});

/** @type {ReadonlyArray<string>} */
export const NATIVE_EVENT_TYPES = Object.freeze(Object.values(NATIVE_EVENT));

/** The two explicit routes W12 may rebind by. Never an implicit third. */
export const RECONCILE_MODE = Object.freeze({
  MOVED: 'moved',
  CLAIM: 'claim',
});

/** @type {ReadonlyArray<string>} */
export const RECONCILE_MODES = Object.freeze(Object.values(RECONCILE_MODE));

/** The closed field set of each NATIVE payload, in canonical order. */
export const REGISTRATION_FIELDS = Object.freeze([
  EVENT_TYPE_FIELD,
  EVENT_VERSION_FIELD,
  'project_id',
  'root',
  'registered_at',
  'registration_receipt_id',
  'marker_sha256',
]);

/** @see REGISTRATION_FIELDS */
export const RECONCILE_FIELDS = Object.freeze([
  EVENT_TYPE_FIELD,
  EVENT_VERSION_FIELD,
  'project_id',
  'from_path',
  'to_path',
  'mode',
  'marker_sha256',
]);

/** @see REGISTRATION_FIELDS */
export const COMMIT_INTENT_EVENT_FIELDS = Object.freeze([
  EVENT_TYPE_FIELD,
  EVENT_VERSION_FIELD,
  'intent',
]);

/**
 * @see REGISTRATION_FIELDS
 *
 * NESTED for exactly the reason the intent is: commit-ack-v1 carries its own `intent_seq`,
 * and a spread payload would put a per-project counter next to the log's total order where
 * one could be read as the other.
 */
export const COMMIT_ACK_EVENT_FIELDS = Object.freeze([
  EVENT_TYPE_FIELD,
  EVENT_VERSION_FIELD,
  'ack',
]);

/**
 * @see REGISTRATION_FIELDS
 *
 * SPREAD rather than nested, unlike the intent and the ack: this payload carries no foreign
 * document and no per-project counter, so there is no second sequence for the log's own
 * `seq` to be confused with. `log_head_seq` is named for what it is - the head of the log
 * that was PACKAGED - so it cannot be read as the position of the event recording it.
 */
export const BUNDLE_EXPORTED_FIELDS = Object.freeze([
  EVENT_TYPE_FIELD,
  EVENT_VERSION_FIELD,
  'target',
  'manifest_sha256',
  'log_head_seq',
]);

/** field set per NATIVE type, so the validator needs no switch of its own. */
const FIELDS_FOR = Object.freeze({
  [NATIVE_EVENT.REGISTRATION]: REGISTRATION_FIELDS,
  [NATIVE_EVENT.RECONCILE]: RECONCILE_FIELDS,
  [NATIVE_EVENT.COMMIT_INTENT]: COMMIT_INTENT_EVENT_FIELDS,
  [NATIVE_EVENT.COMMIT_ACK]: COMMIT_ACK_EVENT_FIELDS,
  [NATIVE_EVENT.BUNDLE_EXPORTED]: BUNDLE_EXPORTED_FIELDS,
});

/** The refusals this module raises when a CALLER hands it something it may not record. */
export const REGISTRY_REFUSAL = Object.freeze({
  NOT_AN_OBJECT: 'REGISTRY_EVENT_NOT_AN_OBJECT',
  TYPE_UNKNOWN: 'REGISTRY_EVENT_TYPE_UNKNOWN',
  VERSION_UNSUPPORTED: 'REGISTRY_EVENT_VERSION_UNSUPPORTED',
  UNKNOWN_FIELD: 'REGISTRY_EVENT_UNKNOWN_FIELD',
  FIELD_MISSING: 'REGISTRY_EVENT_FIELD_MISSING',
  FIELD_MALFORMED: 'REGISTRY_EVENT_FIELD_MALFORMED',
});

/**
 * Why a materialized event was not folded into the view. Each is a REPORT: the bytes stay
 * in the log, and the operator is told which seq was passed over and why.
 */
export const IGNORED_REASON = Object.freeze({
  MALFORMED: 'REGISTRY_IGNORED_MALFORMED',
  DUPLICATE_REGISTRATION: 'REGISTRY_IGNORED_DUPLICATE_REGISTRATION',
  RECONCILE_UNKNOWN_PROJECT: 'REGISTRY_IGNORED_RECONCILE_UNKNOWN_PROJECT',
  INTENT_UNKNOWN_PROJECT: 'REGISTRY_IGNORED_INTENT_UNKNOWN_PROJECT',
  ACK_UNKNOWN_PROJECT: 'REGISTRY_IGNORED_ACK_UNKNOWN_PROJECT',
  ACK_UNKNOWN_INTENT: 'REGISTRY_IGNORED_ACK_UNKNOWN_INTENT',
});

/** Contradictions between two NATIVE events. Both sides are always named. */
export const CONFLICT_KIND = Object.freeze({
  ID_REGISTERED_TWICE: 'REGISTRY_ID_REGISTERED_TWICE',
  ROOT_REGISTERED_TWICE: 'REGISTRY_ROOT_REGISTERED_TWICE',
});

/** A caller-branchable error for a malformed event the caller is trying to CONSTRUCT. */
export class RegistryRefusal extends Error {
  /** @param {string} code @param {string} detail */
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = 'RegistryRefusal';
    this.code = code;
    this.detail = detail;
  }
}

// -- validation ----------------------------------------------------------------

/** @param {unknown} v @returns {boolean} */
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

/** @param {string} code @param {string} field @param {string} detail @returns {object} */
function problem(code, field, detail) {
  return Object.freeze({ code, field, detail, text: `${code}: ${detail}` });
}

/**
 * Is this log event a NATIVE membership event at all?
 *
 * Deliberately permissive about everything else in the log: a DERIVED row (W9) is not
 * malformed, it is simply not this module's business, and reporting it as damage would
 * bury the real damage in noise.
 *
 * @param {unknown} event @returns {boolean}
 */
export function isNativeEvent(event) {
  return Boolean(
    event
      && typeof event === 'object'
      && !Array.isArray(event)
      && NATIVE_EVENT_TYPES.includes(/** @type {any} */ (event)[EVENT_TYPE_FIELD]),
  );
}

/**
 * Validate one NATIVE event payload. Reports every problem rather than the first, because
 * an operator repairing a hand-written recovery log should learn everything wrong with a
 * line in one pass.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, event: object|null, type: string|null, problems: Array<object>}}
 */
export function validateNativeEvent(value) {
  const problems = [];

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    problems.push(problem(
      REGISTRY_REFUSAL.NOT_AN_OBJECT,
      '',
      `a NATIVE event is a JSON object; got ${Array.isArray(value) ? 'an array' : typeof value}`,
    ));
    return { ok: false, event: null, type: null, problems: Object.freeze(problems) };
  }

  const record = /** @type {Record<string, unknown>} */ (value);
  const type = record[EVENT_TYPE_FIELD];

  if (!NATIVE_EVENT_TYPES.includes(/** @type {any} */ (type))) {
    problems.push(problem(
      REGISTRY_REFUSAL.TYPE_UNKNOWN,
      EVENT_TYPE_FIELD,
      `${JSON.stringify(type)} is not one of ${NATIVE_EVENT_TYPES.join(', ')}`,
    ));
    return { ok: false, event: null, type: null, problems: Object.freeze(problems) };
  }

  const fields = FIELDS_FOR[/** @type {string} */ (type)];

  // The field set is CLOSED for the same reason marker-v2's is: a key this engine drops on
  // the next write is a key whose loss nobody can see. Extending means a new event version.
  for (const key of Object.keys(record)) {
    if (!fields.includes(key)) {
      problems.push(problem(
        REGISTRY_REFUSAL.UNKNOWN_FIELD,
        key,
        `${type} v${NATIVE_EVENT_VERSION} is a closed field set and carries no '${key}'`,
      ));
    }
  }
  for (const key of fields) {
    if (!Object.prototype.hasOwnProperty.call(record, key) || record[key] === undefined) {
      problems.push(problem(REGISTRY_REFUSAL.FIELD_MISSING, key, `${key} is absent`));
    }
  }

  if (record[EVENT_VERSION_FIELD] !== undefined && record[EVENT_VERSION_FIELD] !== NATIVE_EVENT_VERSION) {
    problems.push(problem(
      REGISTRY_REFUSAL.VERSION_UNSUPPORTED,
      EVENT_VERSION_FIELD,
      `this engine materializes v${NATIVE_EVENT_VERSION}; got ${JSON.stringify(record[EVENT_VERSION_FIELD])}`,
    ));
  }

  if (type === NATIVE_EVENT.COMMIT_INTENT) {
    if (record.intent !== undefined) {
      const inner = validateCommitIntent(record.intent);
      if (!inner.ok) {
        for (const p of inner.problems) {
          problems.push(problem(REGISTRY_REFUSAL.FIELD_MALFORMED, `intent.${p.field}`, p.detail));
        }
      }
    }
  } else if (type === NATIVE_EVENT.COMMIT_ACK) {
    if (record.ack !== undefined) {
      const inner = validateCommitAck(record.ack);
      if (!inner.ok) {
        for (const p of inner.problems) {
          problems.push(problem(REGISTRY_REFUSAL.FIELD_MALFORMED, `ack.${p.field}`, p.detail));
        }
      }
    }
  } else if (type === NATIVE_EVENT.BUNDLE_EXPORTED) {
    if (record.target !== undefined
      && (!isNonEmptyString(record.target) || !path.isAbsolute(String(record.target)))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'target',
        'the export target must be the absolute path the bundle was written to; a relative '
          + 'value would name a different file from every working directory, and an operator '
          + 'reading this event later needs to be able to go and look at the bytes',
      ));
    }
    if (record.manifest_sha256 !== undefined && !SHA256_PATTERN.test(String(record.manifest_sha256))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'manifest_sha256',
        `${JSON.stringify(record.manifest_sha256)} is not 64 lowercase hex characters. The `
          + 'manifest hash is what lets a bundle found later be matched to the export that '
          + 'wrote it, so an unhashable one records nothing checkable',
      ));
    }
    if (record.log_head_seq !== undefined
      && (!Number.isInteger(record.log_head_seq) || Number(record.log_head_seq) < 0)) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'log_head_seq',
        `${JSON.stringify(record.log_head_seq)} is not a log head sequence. It is the head of `
          + 'the log this bundle carries, and the restore clobber guard compares against it',
      ));
    }
  } else {
    if (record.project_id !== undefined && !PROJECT_ID_PATTERN.test(String(record.project_id))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'project_id',
        `${JSON.stringify(record.project_id)} is not a minted identifier; ids come from the `
          + 'register verb and are never composed from a path or a name',
      ));
    }
    if (record.marker_sha256 !== undefined && !SHA256_PATTERN.test(String(record.marker_sha256))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'marker_sha256',
        `${JSON.stringify(record.marker_sha256)} is not 64 lowercase hex characters`,
      ));
    }
  }

  if (type === NATIVE_EVENT.REGISTRATION) {
    if (record.root !== undefined
      && (!isNonEmptyString(record.root) || !path.isAbsolute(String(record.root)))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'root',
        'the registered root must be the absolute path the directory had at registration; a '
          + 'relative value could not be compared with where a marker is later found',
      ));
    }
    if (record.registered_at !== undefined
      && (!isNonEmptyString(record.registered_at)
        || !TIMESTAMP_PATTERN.test(String(record.registered_at))
        || Number.isNaN(Date.parse(String(record.registered_at))))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'registered_at',
        `${JSON.stringify(record.registered_at)} is not an ISO-8601 UTC instant. It is a record `
          + "for the operator; the log's seq is the sole total order",
      ));
    }
    if (record.registration_receipt_id !== undefined && !isNonEmptyString(record.registration_receipt_id)) {
      problems.push(problem(REGISTRY_REFUSAL.FIELD_MALFORMED, 'registration_receipt_id', 'not a non-empty string'));
    }
  }

  if (type === NATIVE_EVENT.RECONCILE) {
    for (const field of ['from_path', 'to_path']) {
      const value_ = record[field];
      if (value_ !== undefined && (!isNonEmptyString(value_) || !path.isAbsolute(String(value_)))) {
        problems.push(problem(REGISTRY_REFUSAL.FIELD_MALFORMED, field, 'must be an absolute path'));
      }
    }
    if (record.mode !== undefined && !RECONCILE_MODES.includes(/** @type {any} */ (record.mode))) {
      problems.push(problem(
        REGISTRY_REFUSAL.FIELD_MALFORMED,
        'mode',
        `${JSON.stringify(record.mode)} is not one of ${RECONCILE_MODES.join(', ')}; a rebinding `
          + 'always names the explicit route that authorized it',
      ));
    }
  }

  if (problems.length > 0) {
    return { ok: false, event: null, type: /** @type {string} */ (type), problems: Object.freeze(problems) };
  }

  const event = {};
  for (const key of fields) event[key] = record[key];
  return {
    ok: true,
    event: Object.freeze(event),
    type: /** @type {string} */ (type),
    problems: Object.freeze([]),
  };
}

// -- constructors --------------------------------------------------------------

/** @param {{ok: boolean, event: object|null, problems: Array<object>}} result @returns {object} */
function orRefuse(result) {
  if (!result.ok) {
    throw new RegistryRefusal(
      result.problems[0].code,
      result.problems.map((p) => p.text).join('; '),
    );
  }
  return result.event;
}

/**
 * The NATIVE registration event: the ONLY record that a project_id was ever minted.
 *
 * @param {{project_id: string, root: string, registered_at: string,
 *          registration_receipt_id: string, marker_sha256: string}} parts
 * @returns {object} the frozen payload, ready for the W5 append primitive
 */
export function makeRegistrationEvent(parts = /** @type {any} */ ({})) {
  return orRefuse(validateNativeEvent({
    [EVENT_TYPE_FIELD]: NATIVE_EVENT.REGISTRATION,
    [EVENT_VERSION_FIELD]: NATIVE_EVENT_VERSION,
    project_id: parts.project_id,
    root: parts.root === undefined ? undefined : path.resolve(String(parts.root)),
    registered_at: parts.registered_at,
    registration_receipt_id: parts.registration_receipt_id,
    marker_sha256: parts.marker_sha256,
  }));
}

/**
 * The NATIVE reconcile event W12 appends when an operator explicitly rebinds a root.
 * Frozen here, with the materializer that reads it, so the two cannot be written apart.
 *
 * @param {{project_id: string, from_path: string, to_path: string, mode: string,
 *          marker_sha256: string}} parts
 * @returns {object}
 */
export function makeReconcileEvent(parts = /** @type {any} */ ({})) {
  return orRefuse(validateNativeEvent({
    [EVENT_TYPE_FIELD]: NATIVE_EVENT.RECONCILE,
    [EVENT_VERSION_FIELD]: NATIVE_EVENT_VERSION,
    project_id: parts.project_id,
    from_path: parts.from_path === undefined ? undefined : path.resolve(String(parts.from_path)),
    to_path: parts.to_path === undefined ? undefined : path.resolve(String(parts.to_path)),
    mode: parts.mode,
    marker_sha256: parts.marker_sha256,
  }));
}

/**
 * The NATIVE commit-intent event: a commit-intent-v1 carried into the log unchanged.
 *
 * It is NESTED rather than spread, and that is not cosmetic: commit-intent-v1 carries its
 * own per-project `seq`, and the append primitive owns the log's `seq`. Spreading the
 * intent would collide those two, and the primitive refuses the collision by name rather
 * than letting a per-project counter masquerade as the log's total order.
 *
 * @param {object} intent a commit-intent-v1 @returns {object}
 */
export function makeCommitIntentEvent(intent) {
  return orRefuse(validateNativeEvent({
    [EVENT_TYPE_FIELD]: NATIVE_EVENT.COMMIT_INTENT,
    [EVENT_VERSION_FIELD]: NATIVE_EVENT_VERSION,
    intent,
  }));
}

/**
 * The NATIVE commit-ack event: a commit-ack-v1 carried into the log unchanged.
 *
 * The engine CONSTRUCTS this event but does not author its contents - the ack came from the
 * durability layer, and this wraps it for the log without editing a field. Anything the
 * engine "corrected" on the way in would be a claim about durability the engine has no
 * standing to make.
 *
 * @param {object} ack a commit-ack-v1 @returns {object}
 */
export function makeCommitAckEvent(ack) {
  return orRefuse(validateNativeEvent({
    [EVENT_TYPE_FIELD]: NATIVE_EVENT.COMMIT_ACK,
    [EVENT_VERSION_FIELD]: NATIVE_EVENT_VERSION,
    ack,
  }));
}

/**
 * The NATIVE bundle-exported event W16 appends after a bundle is durable on disk.
 *
 * It is appended AFTER the bytes, never before, and that ordering is the whole honesty of
 * the record: an event written first would claim an off-box copy exists in exactly the case
 * where the write then failed, and the degradation banner would go quiet on the strength of
 * a copy nobody has.
 *
 * @param {{target: string, manifest_sha256: string, log_head_seq: number}} parts
 * @returns {object}
 */
export function makeBundleExportedEvent(parts = /** @type {any} */ ({})) {
  return orRefuse(validateNativeEvent({
    [EVENT_TYPE_FIELD]: NATIVE_EVENT.BUNDLE_EXPORTED,
    [EVENT_VERSION_FIELD]: NATIVE_EVENT_VERSION,
    target: parts.target === undefined ? undefined : path.resolve(String(parts.target)),
    manifest_sha256: parts.manifest_sha256,
    log_head_seq: parts.log_head_seq === undefined ? undefined : Number(parts.log_head_seq),
  }));
}

// -- materialization -----------------------------------------------------------

/** @param {object} entry @param {object} patch @returns {object} a new frozen entry */
function withPatch(entry, patch) {
  return Object.freeze({ ...entry, ...patch });
}

/**
 * Materialize membership from log events. PURE: same events in, same view out, forever.
 *
 * This is the function that makes "no second store" checkable rather than claimed. It takes
 * events and returns a value; it opens nothing, caches nothing, and has no way to persist
 * anything. Delete the snapshot, replay the log, and the view is identical - because the
 * view was never anywhere else.
 *
 * @param {Array<object>} events raw log events, in any order (they are replayed by seq)
 * @returns {Readonly<object>} the view
 */
export function materializeRegistry(events = []) {
  const ordered = replayEvents(Array.isArray(events) ? events : []);

  /** @type {Map<string, object>} project_id -> entry */
  const byId = new Map();
  /** @type {Map<string, string>} path key -> project_id */
  const byRoot = new Map();
  // W15. Which per-project intent sequences this replay has SEEN emitted, so an ack naming
  // an intent the log does not carry is reported rather than folded into a watermark. It is
  // local to the replay rather than a field on the entry: the view answers "how far has
  // durability got", and the full emitted run is the log's business, not the view's.
  /** @type {Map<string, Set<number>>} project_id -> emitted intent seqs */
  const intentSeqs = new Map();
  const ignored = [];
  const conflicts = [];
  // W16. Exports are PORTFOLIO facts, not per-project ones: a bundle carries the whole log,
  // so filing it under a project would invent a scope the artifact does not have.
  const bundleExports = [];
  let headSeq = 0;
  let nativeCount = 0;

  for (const raw of ordered) {
    const seq = Number(raw?.[ORDERING_FIELD]);
    if (Number.isFinite(seq) && seq > headSeq) headSeq = seq;
    if (!isNativeEvent(raw)) continue;

    // The primitive's own fields are stripped before validation: the ordering field and the
    // wall clock belong to the log framing, not to the membership payload, and a payload
    // validator that accepted them would accept a hand-written event carrying its own order.
    // Their names are read from the primitive rather than typed, so a rename cannot half-land.
    const payload = {};
    for (const key of Object.keys(raw)) {
      if (key === ORDERING_FIELD || key === WALL_CLOCK_FIELD) continue;
      payload[key] = raw[key];
    }
    const writtenAt = raw[WALL_CLOCK_FIELD] ?? null;
    const check = validateNativeEvent(payload);
    nativeCount += 1;

    if (!check.ok) {
      ignored.push(Object.freeze({
        seq,
        type: raw[EVENT_TYPE_FIELD],
        reason: IGNORED_REASON.MALFORMED,
        status: assertStatusCode(INTEGRITY.UNPARSEABLE, 'registry ignored event'),
        text:
          `log seq ${seq} is a ${raw[EVENT_TYPE_FIELD]} event this engine cannot use `
          + `(${check.problems.map((p) => p.text).join('; ')}). Its bytes remain in the log; it `
          + 'is passed over rather than guessed at.',
      }));
      continue;
    }

    const event = check.event;

    if (check.type === NATIVE_EVENT.REGISTRATION) {
      const id = String(event.project_id);
      const root = path.resolve(String(event.root));
      const existing = byId.get(id) ?? null;

      if (existing !== null) {
        const identical = samePath(existing.root, root)
          && existing.registration_receipt_id === event.registration_receipt_id;
        ignored.push(Object.freeze({
          seq,
          type: check.type,
          reason: IGNORED_REASON.DUPLICATE_REGISTRATION,
          status: assertStatusCode(INTEGRITY.IDENTITY_CONFLICT, 'registry duplicate registration'),
          text:
            `log seq ${seq} registers ${id} again, which was already registered at seq `
            + `${existing.registered_seq}. The FIRST registration stands - an id is minted once - `
            + 'and this event changes no binding.',
        }));
        if (!identical) {
          conflicts.push(Object.freeze({
            kind: CONFLICT_KIND.ID_REGISTERED_TWICE,
            project_id: id,
            status: assertStatusCode(INTEGRITY.IDENTITY_CONFLICT, 'registry id registered twice'),
            paths: Object.freeze([existing.root, root]),
            seqs: Object.freeze([existing.registered_seq, seq]),
            text:
              `project ${id} carries two different registration events: seq `
              + `${existing.registered_seq} at ${existing.root} and seq ${seq} at ${root}. Both are `
              + 'named, the first binding is kept, and the project is counted exactly once.',
          }));
        }
        continue;
      }

      const heldBy = byRoot.get(pathKey(root)) ?? null;
      if (heldBy !== null && heldBy !== id) {
        conflicts.push(Object.freeze({
          kind: CONFLICT_KIND.ROOT_REGISTERED_TWICE,
          project_id: heldBy,
          other_project_id: id,
          status: assertStatusCode(INTEGRITY.IDENTITY_CONFLICT, 'registry root registered twice'),
          paths: Object.freeze([root]),
          seqs: Object.freeze([seq]),
          text:
            `${root} is registered under ${heldBy} and log seq ${seq} registers it again under `
            + `${id}. Both ids are named and neither claim is silently preferred; the register `
            + 'verb refuses this case, so a log carrying it was written by something else.',
        }));
      }

      const entry = Object.freeze({
        project_id: id,
        root,
        current_path: root,
        registered_at: String(event.registered_at),
        registration_receipt_id: String(event.registration_receipt_id),
        marker_sha256: String(event.marker_sha256),
        registered_seq: seq,
        registered_written_at: writtenAt ?? null,
        moves: Object.freeze([]),
        commit_intent_seq: null,
        commit_intent_count: 0,
        // W15. The acknowledged-commit watermark, stated as its own pair of facts beside
        // the emitted ones. Two numbers rather than one boolean, because "we asked" and
        // "somebody did it" are the two different facts this whole wave is about, and a
        // view that carried only their difference could not name which is which.
        commit_ack_seq: null,
        commit_ack_count: 0,
        acked_intent_seqs: Object.freeze([]),
        // Presence is a question about the FILESYSTEM and this module never touches one, so
        // it is stated as unanswered here rather than assumed live. W11's root-status
        // classifier is what fills it in, and a view that guessed would make an unplugged
        // share indistinguishable from a live root.
        presence: assertStatusCode(PRESENCE.UNREACHABLE, 'registry entry presence'),
        freshness: assertStatusCode(FRESHNESS.UNKNOWN, 'registry entry freshness'),
      });
      byId.set(id, entry);
      if (heldBy === null) byRoot.set(pathKey(root), id);
      continue;
    }

    if (check.type === NATIVE_EVENT.RECONCILE) {
      const id = String(event.project_id);
      const entry = byId.get(id) ?? null;
      if (entry === null) {
        ignored.push(Object.freeze({
          seq,
          type: check.type,
          reason: IGNORED_REASON.RECONCILE_UNKNOWN_PROJECT,
          status: assertStatusCode(FRESHNESS.UNKNOWN, 'registry reconcile without registration'),
          text:
            `log seq ${seq} reconciles ${id}, which no registration event in this log ever `
            + 'minted. A rebinding cannot create membership, so it is reported rather than applied.',
        }));
        continue;
      }
      const to = path.resolve(String(event.to_path));
      const from = path.resolve(String(event.from_path));
      const move = Object.freeze({
        seq,
        from_path: from,
        to_path: to,
        mode: String(event.mode),
        marker_sha256: String(event.marker_sha256),
      });
      if (byRoot.get(pathKey(entry.current_path)) === id) byRoot.delete(pathKey(entry.current_path));
      byRoot.set(pathKey(to), id);
      byId.set(id, withPatch(entry, {
        current_path: to,
        moves: Object.freeze([...entry.moves, move]),
      }));
      continue;
    }

    if (check.type === NATIVE_EVENT.COMMIT_INTENT) {
      const intent = event.intent;
      const id = String(intent.project_id);
      const entry = byId.get(id) ?? null;
      if (entry === null) {
        ignored.push(Object.freeze({
          seq,
          type: check.type,
          reason: IGNORED_REASON.INTENT_UNKNOWN_PROJECT,
          status: assertStatusCode(FRESHNESS.UNKNOWN, 'registry intent without registration'),
          text:
            `log seq ${seq} carries a ${COMMIT_INTENT_SCHEMA} for ${id}, which no registration `
            + 'event in this log ever minted; it is reported and counted, never folded into a '
            + 'membership this log has no record of.',
        }));
        continue;
      }
      const emitted = intentSeqs.get(id) ?? new Set();
      emitted.add(Number(intent.seq));
      intentSeqs.set(id, emitted);
      byId.set(id, withPatch(entry, {
        commit_intent_seq: Number(intent.seq),
        commit_intent_count: entry.commit_intent_count + 1,
      }));
      continue;
    }

    if (check.type === NATIVE_EVENT.BUNDLE_EXPORTED) {
      bundleExports.push(Object.freeze({
        seq,
        target: String(event.target),
        manifest_sha256: String(event.manifest_sha256),
        log_head_seq: Number(event.log_head_seq),
        written_at: writtenAt ?? null,
      }));
      continue;
    }

    // NATIVE_EVENT.COMMIT_ACK
    const ack = event.ack;
    const id = String(ack.project_id);
    const entry = byId.get(id) ?? null;
    if (entry === null) {
      ignored.push(Object.freeze({
        seq,
        type: check.type,
        reason: IGNORED_REASON.ACK_UNKNOWN_PROJECT,
        status: assertStatusCode(FRESHNESS.UNKNOWN, 'registry ack without registration'),
        text:
          `log seq ${seq} carries a ${COMMIT_ACK_SCHEMA} for ${id}, which no registration event `
          + 'in this log ever minted. An acknowledgement cannot create membership, so it is '
          + 'reported rather than applied.',
      }));
      continue;
    }
    const emitted = intentSeqs.get(id) ?? new Set();
    if (!emitted.has(Number(ack.intent_seq))) {
      // The ack is well-formed and says something this log cannot confirm. That is a fact
      // for the operator - a restored-from-backup log, or an acknowledgement of an intent
      // that was written and lost - and NOT a watermark. Believing it would raise the
      // durability floor on the strength of bytes nothing here can check.
      ignored.push(Object.freeze({
        seq,
        type: check.type,
        reason: IGNORED_REASON.ACK_UNKNOWN_INTENT,
        status: assertStatusCode(FRESHNESS.UNKNOWN, 'registry ack without its intent'),
        text:
          `log seq ${seq} acknowledges intent ${ack.intent_seq} of ${id}, which no `
          + `${COMMIT_INTENT_SCHEMA} in this log emitted. The acknowledgement is recorded in the `
          + 'log and named here; it does not advance the watermark, because a floor raised on '
          + 'an intent this log never wrote would be a durability claim nothing can check.',
      }));
      continue;
    }
    const ackedSeq = Number(ack.intent_seq);
    const acked = entry.acked_intent_seqs.includes(ackedSeq)
      ? entry.acked_intent_seqs
      : [...entry.acked_intent_seqs, ackedSeq].sort((a, b) => a - b);
    byId.set(id, withPatch(entry, {
      // The watermark only ever RISES. A later ack naming an earlier intent is a legitimate
      // catch-up, not a retraction, and lowering the floor for it would make durability
      // appear to go backwards while nothing was lost.
      commit_ack_seq: entry.commit_ack_seq === null
        ? ackedSeq
        : Math.max(entry.commit_ack_seq, ackedSeq),
      commit_ack_count: entry.commit_ack_count + 1,
      acked_intent_seqs: Object.freeze(acked),
    }));
  }

  const projects = [...byId.keys()].sort().map((id) => byId.get(id));

  return Object.freeze({
    version: REGISTRY_VERSION,
    head_seq: headSeq,
    projects: Object.freeze(projects),
    project_count: projects.length,
    row_count: projects.length,
    project_ids: Object.freeze(projects.map((p) => p.project_id)),
    conflicts: Object.freeze(conflicts),
    ignored: Object.freeze(ignored),
    native_event_count: nativeCount,
    // Every export this log records, in replay order, and the latest of them. A surface asks
    // the view "when did a copy last leave the box"; it never asks a directory listing, which
    // would answer for whichever bundle happens still to be lying around.
    bundle_exports: Object.freeze(bundleExports),
    last_bundle_export: bundleExports.length > 0 ? bundleExports[bundleExports.length - 1] : null,
  });
}

// -- lookups -------------------------------------------------------------------

/**
 * Resolve a project_id to its entry. This IS the "still resolves" the W7 invariant asserts
 * after every mutating operation: an id that once appeared in the view and later resolves
 * to nothing means membership was lost, whatever the row count says.
 *
 * @param {Readonly<object>} view @param {string} projectId @returns {object|null}
 */
export function resolveProject(view, projectId) {
  if (!view || !Array.isArray(view.projects)) return null;
  const id = String(projectId);
  return view.projects.find((p) => p.project_id === id) ?? null;
}

/**
 * Resolve a directory to the project registered there, comparing paths by the NG-3 key so
 * `<path> and `<path> are one directory.
 *
 * @param {Readonly<object>} view @param {string} rootPath @returns {object|null}
 */
export function resolveRoot(view, rootPath) {
  if (!view || !Array.isArray(view.projects)) return null;
  const key = pathKey(rootPath);
  return (
    view.projects.find((p) => pathKey(p.current_path) === key)
    ?? view.projects.find((p) => pathKey(p.root) === key)
    ?? null
  );
}

/** @param {Readonly<object>} view @returns {number} the portfolio's membership row count */
export function registryRowCount(view) {
  return view && Array.isArray(view.projects) ? view.projects.length : 0;
}

/** @param {Readonly<object>} view @returns {string[]} every project_id in the view, sorted */
export function registryProjectIds(view) {
  return view && Array.isArray(view.projects) ? view.projects.map((p) => p.project_id) : [];
}

/**
 * The highest per-project commit-intent sequence the log records for a project, or null.
 * W15 reads this to find the acknowledged-commit watermark; W7 reads it to allocate the
 * next intent without a counter of its own.
 *
 * @param {Readonly<object>} view @param {string} projectId @returns {number|null}
 */
export function lastCommitIntentSeq(view, projectId) {
  const entry = resolveProject(view, projectId);
  return entry === null ? null : entry.commit_intent_seq;
}

/**
 * The highest per-project commit-intent sequence the log records as ACKNOWLEDGED, or null.
 *
 * This is the watermark W15's health reads and W17 recovers to. It is a different question
 * from lastCommitIntentSeq() and the two are deliberately separate functions rather than
 * one function with a flag: 'receipt written' and 'receipt honored' are different facts,
 * and a call site that can confuse them at the keyword level eventually will.
 *
 * @param {Readonly<object>} view @param {string} projectId @returns {number|null}
 */
export function lastCommitAckSeq(view, projectId) {
  const entry = resolveProject(view, projectId);
  return entry === null ? null : entry.commit_ack_seq;
}

// -- reading the view ----------------------------------------------------------

/**
 * Materialize the view from the ONE log.
 *
 * The snapshot is not consulted, and that is the point rather than an omission: the
 * snapshot is derived from these same events, so reading it would be asking one question
 * twice and then having to decide which answer to believe. An index that cannot be read is
 * reported with the append-log module's own failure row - never as a portfolio of zero
 * projects, which is the exact lie the loud-unknown criterion exists to forbid.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, boundMs?: number,
 *          staleMs?: number, quarantine?: boolean, lockOpts?: object}} [opts]
 * @returns {Readonly<{ok: boolean, view: object|null, outcome: object, head_seq: number}>}
 */
export function readRegistry(opts = {}) {
  const outcome = openIndexForRead(opts);
  if (outcome.ok !== true) {
    return Object.freeze({ ok: false, view: null, outcome, head_seq: 0 });
  }
  const view = materializeRegistry(outcome.events ?? []);
  return Object.freeze({
    ok: true,
    view,
    outcome,
    head_seq: outcome.head_seq ?? view.head_seq,
  });
}

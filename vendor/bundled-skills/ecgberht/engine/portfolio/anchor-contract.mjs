/**
 * W15 - the Anchor contract: what the engine promises, what it may not claim, and how loudly
 * it says the difference.
 *
 * THE ONE SENTENCE THIS MODULE EXISTS TO KEEP HONEST. 'receipt written' and 'receipt
 * honored' are different facts. The engine writes a project file, fsyncs it, derives a row,
 * and appends a commit-intent asking that those exact bytes be made durable somewhere that
 * is not this disk. It does not, and cannot, know whether that happened. Anchor - a separate
 * effort, a separate release, a separate repository - is what honors an intent, and the only
 * evidence the engine will ever have is an acknowledgement handed back to it.
 *
 * SO THE ENGINE STATES TWO NUMBERS, NEVER ONE. The highest EMITTED intent per project, and
 * the highest ACKNOWLEDGED one. Everything between them is work whose only copy is local
 * disk. A system that carried only the first number would let a steward believe a year of
 * receipts were safe off-box while nothing had ever left the machine, and it would believe it
 * silently, which is the failure mode worth building a wave against.
 *
 * WHY ONE BANNER AND NOT FORTY WARNINGS. Per-intent warnings scale with the thing that is
 * wrong: a portfolio that has been unacknowledged for a fortnight produces hundreds of them,
 * which is a wall of text nobody reads, which is zero warnings with extra steps. This module
 * emits exactly ONE line whose loudness rises with the age of the OLDEST unacknowledged
 * intent (the ladder is frozen in status.mjs, beside the sentence). Age is what escalates,
 * because age is what the operator can still act on.
 *
 * WHAT DEGRADED MEANS HERE, precisely: an intent older than the ack threshold has no
 * acknowledgement. Not "the index is broken" - the index is fine, every file is intact and
 * every row is findable. DEGRADED is a statement about DURABILITY, and the banner says the
 * true thing rather than the alarming one: local disk is currently the only copy.
 *
 * WHAT THIS MODULE MAY NOT DO, and the sweep test that proves it: it never invokes the
 * durability layer. No process is spawned, no library is imported, no command is run. The
 * engine's whole side of this contract is bytes in a log; anything more would make the
 * engine responsible for a tool it cannot version, on a machine it cannot inspect.
 * test/w5x-engine-git-free.test.mjs is the permanent guard on that line.
 *
 * C7b IS OPEN AND SAYS SO. The other side of this contract - Anchor actually honoring the
 * intents - is not in this repository and is not closeable here. Every surface that shows
 * durability reports that openly (see C7B_STATUS below) rather than rendering an
 * unacknowledged portfolio as if the contract were complete.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

import { appendEvents, openIndexForRead, indexPathsFrom } from '../append-log.mjs';
import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from '../durable-write.mjs';
import { exportRecency } from './bundle.mjs';
import { COMMIT_ACK_SCHEMA, validateCommitAck } from './commit-ack.mjs';
import { COMMIT_INTENT_SCHEMA, commitIntentHash } from './commit-intent.mjs';
import {
  EVENT_TYPE_FIELD,
  NATIVE_EVENT,
  makeCommitAckEvent,
  materializeRegistry,
} from './registry.mjs';
import {
  COMPOSITE,
  DEGRADED_SEVERITY,
  FRESHNESS,
  INTEGRITY,
  assertStatusCode,
  degradedSeverityFor,
  renderDegraded,
} from './status.mjs';
import { refreshBadgeCacheAfterAttentionPush } from './badge-cache.mjs';

/** This wave's frozen version. The two-sided fixture set is stamped with it. */
export const ANCHOR_CONTRACT_VERSION = 'anchor-contract-v1';

/** One day, in milliseconds. The ladder's unit. */
export const MS_PER_DAY = 86_400_000;

/**
 * How long an intent may go unacknowledged before durability is DEGRADED.
 *
 * One day, and the reasoning is stated rather than tuned: the acknowledging side is meant to
 * run continuously, so a full day of silence is not latency, it is a stopped process. A
 * threshold measured in minutes would fire on a laptop that was closed over lunch; one
 * measured in weeks would let a month of work sit on a single disk unmentioned.
 */
export const ACK_THRESHOLD_DAYS = 1;

/**
 * The open status of the other side, carried onto every durability surface.
 *
 * It is a VALUE rather than a comment because a comment cannot be rendered, and the point is
 * that an operator reading the High Seat learns the contract is one-sided today. `open` stays
 * true until the acknowledging release ships; nothing in this repository can flip it.
 */
export const C7B_STATUS = Object.freeze({
  criterion: 'C7b',
  open: true,
  owner: 'anchor',
  text:
    'C7b is OPEN: the engine emits commit-intents and accepts acknowledgements, but the side '
    + 'that honours them ships from another repository. Until an acknowledgement arrives, a '
    + 'receipt is written and not yet committed.',
});

/** The phrase the stand-up and the High Seat show for an unacknowledged intent. */
export const NOT_YET_COMMITTED = 'state not yet committed';

/** The outcomes ack ingestion reports. Every one is a named row, never a thrown surprise. */
export const ANCHOR_CODE = Object.freeze({
  ACK_ACCEPTED: 'ANCHOR_ACK_ACCEPTED',
  ACK_MALFORMED: 'ANCHOR_ACK_MALFORMED',
  ACK_UNKNOWN_PROJECT: 'ANCHOR_ACK_UNKNOWN_PROJECT',
  ACK_NO_SUCH_INTENT: 'ANCHOR_ACK_NO_SUCH_INTENT',
  ACK_HASH_DISAGREES: 'ANCHOR_ACK_HASH_DISAGREES',
  ACK_DUPLICATE: 'ANCHOR_ACK_DUPLICATE',
  ACK_APPEND_FAILED: 'ANCHOR_ACK_APPEND_FAILED',
  INDEX_UNREADABLE: 'ANCHOR_INDEX_UNREADABLE',
});

/** The user-visible sentence per row. Read, never composed at the call site. */
export const ANCHOR_ROWS = Object.freeze({
  [ANCHOR_CODE.ACK_ACCEPTED]: {
    status: INTEGRITY.OK,
    text:
      'acknowledgement recorded: intent {intent_seq} of {project_id} is durable off this box '
      + 'as {commit_id}.',
  },
  [ANCHOR_CODE.ACK_MALFORMED]: {
    status: INTEGRITY.UNPARSEABLE,
    text:
      'the acknowledgement is not a {schema} ({reason}). It is refused rather than stored, '
      + 'because an unparseable ack folded into the watermark would raise the durability floor '
      + 'on bytes nobody can read.',
  },
  [ANCHOR_CODE.ACK_UNKNOWN_PROJECT]: {
    status: FRESHNESS.UNKNOWN,
    text:
      'the acknowledgement names project {project_id}, which no registration event in this log '
      + 'ever minted. An acknowledgement cannot create membership.',
  },
  [ANCHOR_CODE.ACK_NO_SUCH_INTENT]: {
    status: FRESHNESS.UNKNOWN,
    text:
      'the acknowledgement honours intent {intent_seq} of {project_id}, which this log never '
      + 'emitted. It is refused: a durability floor raised on an intent this engine did not '
      + 'write is a claim nothing here can check.',
  },
  [ANCHOR_CODE.ACK_HASH_DISAGREES]: {
    status: INTEGRITY.TAMPERED,
    text:
      'the acknowledgement claims intent {intent_seq} of {project_id} with hash {claimed}, but '
      + 'this log records {recorded}. Two different receipts carry that number - one of these '
      + 'logs is not the one that was committed - so nothing is acknowledged until an operator '
      + 'says which.',
  },
  [ANCHOR_CODE.ACK_DUPLICATE]: {
    status: INTEGRITY.OK,
    text:
      'intent {intent_seq} of {project_id} is already acknowledged by this log; the repeated '
      + 'acknowledgement is reported and not appended a second time.',
  },
  [ANCHOR_CODE.ACK_APPEND_FAILED]: {
    status: INTEGRITY.UNPARSEABLE,
    text:
      'the acknowledgement is valid but could not be made durable in the log ({reason}). It is '
      + 'NOT counted: the watermark says what the log records, and nothing else.',
  },
  [ANCHOR_CODE.INDEX_UNREADABLE]: {
    status: FRESHNESS.UNKNOWN,
    text:
      'the index could not be read, so no acknowledgement can be checked against a lineage '
      + '({reason}). Durability is reported as unanswered rather than as healthy.',
  },
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) => (
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole
  ));
}

/**
 * One outcome, worded from the frozen row.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function anchorOutcome(code, params = {}, extra = {}) {
  const row = ANCHOR_ROWS[code];
  if (row === undefined) throw new Error(`anchor-contract: ${code} is not a frozen row`);
  return Object.freeze({
    ok: code === ANCHOR_CODE.ACK_ACCEPTED || code === ANCHOR_CODE.ACK_DUPLICATE,
    code,
    status: assertStatusCode(row.status, `anchor row ${code}`),
    text: fill(row.text, { schema: COMMIT_ACK_SCHEMA, ...params }),
    ...extra,
  });
}

// -- reading the two sides out of the log --------------------------------------

/** @param {unknown} event @param {string} type @returns {boolean} */
function isType(event, type) {
  return Boolean(event && typeof event === 'object' && event[EVENT_TYPE_FIELD] === type);
}

/**
 * Every commit-intent the log carries, with the facts the ladder and the watermark need.
 *
 * `written_at` is read from the INTENT rather than from the log framing, because the intent's
 * own wall clock is what the receipt claims about itself, and it is the value an operator
 * sees quoted back. It orders nothing: the list comes out in log order, which is `seq` order,
 * which is the sole total order (NG-4).
 *
 * @param {Array<object>} events
 * @returns {ReadonlyArray<{log_seq: number, project_id: string, intent_seq: number,
 *          reason: string, written_at: string, sha256: string, paths: ReadonlyArray<object>}>}
 */
export function commitIntentsIn(events = []) {
  const out = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (!isType(event, NATIVE_EVENT.COMMIT_INTENT)) continue;
    const intent = event.intent;
    if (!intent || typeof intent !== 'object') continue;
    out.push(Object.freeze({
      log_seq: Number(event.seq ?? 0),
      project_id: String(intent.project_id),
      intent_seq: Number(intent.seq),
      reason: String(intent.reason),
      written_at: String(intent.written_at ?? event.written_at ?? ''),
      sha256: commitIntentHash(intent),
      paths: Object.freeze((intent.paths ?? []).map((p) => Object.freeze({ ...p }))),
    }));
  }
  return Object.freeze(out);
}

/**
 * Every acknowledgement the log carries.
 *
 * @param {Array<object>} events
 * @returns {ReadonlyArray<{log_seq: number, project_id: string, intent_seq: number,
 *          intent_sha256: string, commit_id: string, anchor: string, acked_at: string}>}
 */
export function commitAcksIn(events = []) {
  const out = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (!isType(event, NATIVE_EVENT.COMMIT_ACK)) continue;
    const ack = event.ack;
    if (!ack || typeof ack !== 'object') continue;
    out.push(Object.freeze({
      log_seq: Number(event.seq ?? 0),
      project_id: String(ack.project_id),
      intent_seq: Number(ack.intent_seq),
      intent_sha256: String(ack.intent_sha256),
      commit_id: String(ack.commit_id),
      anchor: String(ack.anchor),
      acked_at: String(ack.acked_at ?? ''),
    }));
  }
  return Object.freeze(out);
}

/** @param {string} projectId @param {number} intentSeq @returns {string} */
function intentKey(projectId, intentSeq) {
  return `${projectId}#${intentSeq}`;
}

/**
 * The two sides, joined: which intents are acknowledged, which are still only local.
 *
 * An ack joins to an intent on (project_id, intent_seq) AND the recorded hash. The hash is
 * not belt-and-braces: a log restored from an older copy can hold a DIFFERENT intent number
 * four, and an ack matched on the number alone would silently mark the wrong receipt safe.
 *
 * @param {Array<object>} events raw log events
 * @returns {Readonly<{intents: ReadonlyArray<object>, acks: ReadonlyArray<object>,
 *          acknowledged: ReadonlyArray<object>, unacknowledged: ReadonlyArray<object>,
 *          disagreements: ReadonlyArray<object>, orphan_acks: ReadonlyArray<object>,
 *          per_project: Readonly<Record<string, object>>}>}
 */
export function intentLedger(events = []) {
  const intents = commitIntentsIn(events);
  const acks = commitAcksIn(events);

  /** @type {Map<string, object>} */
  const byKey = new Map();
  for (const intent of intents) byKey.set(intentKey(intent.project_id, intent.intent_seq), intent);

  /** @type {Set<string>} */
  const ackedKeys = new Set();
  const disagreements = [];
  const orphans = [];

  for (const ack of acks) {
    const key = intentKey(ack.project_id, ack.intent_seq);
    const intent = byKey.get(key) ?? null;
    if (intent === null) {
      orphans.push(ack);
      continue;
    }
    if (intent.sha256 !== ack.intent_sha256) {
      disagreements.push(Object.freeze({ ack, intent }));
      continue;
    }
    ackedKeys.add(key);
  }

  const acknowledged = intents.filter((i) => ackedKeys.has(intentKey(i.project_id, i.intent_seq)));
  const unacknowledged = intents.filter((i) => !ackedKeys.has(intentKey(i.project_id, i.intent_seq)));

  /** @type {Record<string, object>} */
  const perProject = {};
  for (const intent of intents) {
    const entry = perProject[intent.project_id] ?? {
      project_id: intent.project_id,
      emitted: 0,
      acknowledged: 0,
      unacknowledged: 0,
      emitted_seq: null,
      ack_seq: null,
      oldest_unacked: null,
    };
    entry.emitted += 1;
    entry.emitted_seq = entry.emitted_seq === null
      ? intent.intent_seq
      : Math.max(entry.emitted_seq, intent.intent_seq);
    if (ackedKeys.has(intentKey(intent.project_id, intent.intent_seq))) {
      entry.acknowledged += 1;
      entry.ack_seq = entry.ack_seq === null
        ? intent.intent_seq
        : Math.max(entry.ack_seq, intent.intent_seq);
    } else {
      entry.unacknowledged += 1;
      if (entry.oldest_unacked === null) entry.oldest_unacked = intent;
    }
    perProject[intent.project_id] = entry;
  }
  for (const id of Object.keys(perProject)) perProject[id] = Object.freeze(perProject[id]);

  return Object.freeze({
    intents,
    acks,
    acknowledged: Object.freeze(acknowledged),
    unacknowledged: Object.freeze(unacknowledged),
    disagreements: Object.freeze(disagreements),
    orphan_acks: Object.freeze(orphans),
    per_project: Object.freeze(perProject),
  });
}

/**
 * The acknowledged-commit watermark per project: the highest intent sequence this log can
 * prove left the machine, and the portfolio floor beneath all of them.
 *
 * Unlike the W14 placeholder of the same shape, this reads ACKS. `basis` says which of the
 * two it is on every run, so nobody has to guess whether a number is a promise or a receipt.
 *
 * @param {Array<object>} events
 * @returns {Readonly<{per_project: Readonly<Record<string, number|null>>, floor: number|null,
 *          basis: string}>}
 */
export function ackWatermark(events = []) {
  const ledger = intentLedger(events);
  /** @type {Record<string, number|null>} */
  const perProject = {};
  const ids = Object.keys(ledger.per_project).sort();
  for (const id of ids) perProject[id] = ledger.per_project[id].ack_seq;

  // The FLOOR is the weakest project, and one project with nothing acknowledged puts the
  // whole portfolio's floor at null. That is deliberate and it is the honest reading: a
  // portfolio-level number is only as strong as its worst member, and averaging or ignoring
  // the unacknowledged project would let one project's silence hide behind another's health.
  const values = ids.map((id) => perProject[id]);
  const floor = values.length === 0 || values.some((v) => v === null)
    ? null
    : Math.min(...(/** @type {number[]} */ (values)));

  return Object.freeze({
    per_project: Object.freeze(perProject),
    floor,
    basis: 'HIGHEST_ACKNOWLEDGED_COMMIT_INTENT',
  });
}

// -- ack ingestion --------------------------------------------------------------

/**
 * Record one acknowledgement handed back by the durability layer.
 *
 * It is a full round trip rather than an append: the ack is validated as a document, joined
 * to the lineage this log actually holds, and only then written. Each refusal is a distinct
 * named row because the operator acts differently on each - a malformed ack is a bug in the
 * acknowledging release, an unknown intent is a log that has been restored or lost events,
 * and a hash disagreement is two histories claiming the same number.
 *
 * @param {{ack: object, home?: string, paths?: object, env?: object, fsx?: object,
 *          now?: number|Date, boundMs?: number, staleMs?: number, quarantine?: boolean,
 *          lockOpts?: object}} req
 * @returns {Readonly<object>}
 */
export function ingestAck(req) {
  const opts = req ?? {};
  const checked = validateCommitAck(opts.ack);
  if (!checked.ok) {
    return anchorOutcome(ANCHOR_CODE.ACK_MALFORMED, {
      reason: checked.problems.map((p) => p.text).join('; '),
    }, { ack: null, appended: false, problems: checked.problems });
  }
  const ack = checked.ack;

  const read = openIndexForRead(opts);
  if (read.ok !== true) {
    return anchorOutcome(ANCHOR_CODE.INDEX_UNREADABLE, {
      reason: read.text ? read.text : String(read.code),
    }, { ack, appended: false, index_outcome: read });
  }

  const events = read.events ?? [];
  const view = materializeRegistry(events);
  if (!view.project_ids.includes(ack.project_id)) {
    return anchorOutcome(ANCHOR_CODE.ACK_UNKNOWN_PROJECT, {
      project_id: ack.project_id,
      intent_seq: ack.intent_seq,
    }, { ack, appended: false });
  }

  const ledger = intentLedger(events);
  const intent = ledger.intents.find(
    (i) => i.project_id === ack.project_id && i.intent_seq === ack.intent_seq,
  ) ?? null;
  if (intent === null) {
    return anchorOutcome(ANCHOR_CODE.ACK_NO_SUCH_INTENT, {
      project_id: ack.project_id,
      intent_seq: ack.intent_seq,
    }, { ack, appended: false });
  }
  if (intent.sha256 !== ack.intent_sha256) {
    return anchorOutcome(ANCHOR_CODE.ACK_HASH_DISAGREES, {
      project_id: ack.project_id,
      intent_seq: ack.intent_seq,
      claimed: ack.intent_sha256,
      recorded: intent.sha256,
    }, { ack, intent, appended: false });
  }

  const already = ledger.acknowledged.some(
    (i) => i.project_id === ack.project_id && i.intent_seq === ack.intent_seq,
  );
  if (already) {
    return anchorOutcome(ANCHOR_CODE.ACK_DUPLICATE, {
      project_id: ack.project_id,
      intent_seq: ack.intent_seq,
    }, { ack, intent, appended: false });
  }

  const appended = appendEvents([makeCommitAckEvent(ack)], opts);
  if (appended.ok !== true) {
    return anchorOutcome(ANCHOR_CODE.ACK_APPEND_FAILED, {
      reason: appended.text ? appended.text : String(appended.code),
    }, { ack, intent, appended: false, index_outcome: appended });
  }

  return anchorOutcome(ANCHOR_CODE.ACK_ACCEPTED, {
    project_id: ack.project_id,
    intent_seq: ack.intent_seq,
    commit_id: ack.commit_id,
  }, {
    ack,
    intent,
    appended: true,
    seq: appended.seq,
    head_seq: appended.head_seq,
    index_outcome: appended,
  });
}

// -- Wave 16: attention projection index bridge ----------------------------------
//
// Wave-3 A5 probe recorded NEEDS-WIRE: ingestAck is in-process only and there was
// no bridge for typed attention into the portfolio index. Wave 16 wires the
// PROJECT-PUSHES path: publishAttention calls pushAttentionProjection so the
// already-built index receives the cell without walking project roots.
// Durable helpers: writeFileAtomicSync + withFileLock (S9).

/** Relative directory under the index home for pushed attention cells. */
export const ATTENTION_INDEX_REL = 'attention';

/** Schema for an index-side attention projection cell. */
export const ATTENTION_INDEX_SCHEMA = 'ecgberht-attention-index-cell-v0';

/**
 * Stable key for an attention push (project_id preferred; path hash fallback).
 * @param {{ project_id?: string|null, project_path?: string|null }} req
 * @returns {string|null}
 */
export function attentionIndexKey(req = {}) {
  if (req.project_id != null && String(req.project_id).length > 0) {
    return String(req.project_id);
  }
  if (req.project_path != null && String(req.project_path).length > 0) {
    return crypto
      .createHash('sha256')
      .update(path.resolve(String(req.project_path)))
      .digest('hex')
      .slice(0, 32);
  }
  return null;
}

/**
 * Absolute path of the index-side attention cell.
 * @param {string} home index home
 * @param {string} key
 */
export function attentionIndexCellPath(home, key) {
  return path.join(home, ATTENTION_INDEX_REL, `${key}.json`);
}

/**
 * PROJECT PUSHES a typed attention projection into the portfolio index home.
 * The index never walks project roots for this path — delivery is push-only.
 *
 * Uses the same durable helpers as the rest of the index side
 * (withFileLock + writeFileAtomicSync). Edge-only: identical edge_hash leaves
 * the cell byte-identical and reports pushed:false.
 *
 * @param {{
 *   project_id?: string|null,
 *   project_path?: string|null,
 *   attention: object,
 *   home?: string,
 *   paths?: object,
 *   env?: object,
 * }} req
 * @returns {Readonly<object>}
 */
export function pushAttentionProjection(req = {}) {
  const attention = req.attention;
  if (!attention || typeof attention !== 'object') {
    return Object.freeze({
      ok: false,
      code: 'ATTENTION_PUSH_MALFORMED',
      pushed: false,
      reason: 'attention cell required',
      bridge: 'pushAttentionProjection',
    });
  }

  const key = attentionIndexKey(req);
  if (!key) {
    return Object.freeze({
      ok: false,
      code: 'ATTENTION_PUSH_NO_KEY',
      pushed: false,
      reason: 'project_id or project_path required for index key',
      bridge: 'pushAttentionProjection',
    });
  }

  let paths;
  try {
    paths = req.paths ?? indexPathsFrom({ home: req.home, env: req.env });
  } catch (e) {
    return Object.freeze({
      ok: false,
      code: 'ATTENTION_PUSH_HOME_REFUSED',
      pushed: false,
      reason: String(e?.message ?? e),
      bridge: 'pushAttentionProjection',
    });
  }
  const home = paths?.home ?? req.home;
  if (!home || typeof home !== 'string') {
    return Object.freeze({
      ok: false,
      code: 'ATTENTION_PUSH_HOME_REFUSED',
      pushed: false,
      reason: 'index home unresolved',
      bridge: 'pushAttentionProjection',
    });
  }

  const cellPath = attentionIndexCellPath(home, key);
  const payload = {
    schema: ATTENTION_INDEX_SCHEMA,
    project_id: req.project_id ?? null,
    project_path: req.project_path != null ? path.resolve(String(req.project_path)) : null,
    key,
    state: attention.state ?? null,
    state_since: attention.state_since ?? null,
    reason: attention.reason ?? null,
    edge_hash: attention.edge_hash ?? null,
    client_event_id: attention.client_event_id ?? null,
    waiting_steps: attention.waiting_steps ?? 0,
    bundle_hash: attention.bundle_hash ?? null,
    failure_code: attention.failure_code ?? null,
    // The commissioned-run briefing rides to the index so the High Seat's
    // raise can say did / question / next without opening the project.
    briefing: attention.briefing ?? null,
    at: attention.at ?? new Date().toISOString(),
    pushed_via: 'publishAttention',
    bridge: 'pushAttentionProjection',
    // Project pushes; the index never walks.
    index_walks_roots: false,
  };
  const bytes = `${JSON.stringify(payload, null, 2)}\n`;

  try {
    // Edge-only: identical content → no rewrite.
    if (fs.existsSync(cellPath)) {
      const prior = fs.readFileSync(cellPath, 'utf8');
      if (prior === bytes) {
        return Object.freeze({
          ok: true,
          pushed: false,
          reason: 'no_edge_change',
          key,
          path: cellPath,
          cell: payload,
          bridge: 'pushAttentionProjection',
          index_walks_roots: false,
          idempotent: true,
        });
      }
    }

    withFileLock(
      cellPath,
      () => {
        fs.mkdirSync(path.dirname(cellPath), { recursive: true });
        writeFileAtomicSync(cellPath, bytes);
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return Object.freeze({
      ok: false,
      code: 'ATTENTION_PUSH_FAILED',
      pushed: false,
      reason: String(e?.message ?? e),
      key,
      path: cellPath,
      bridge: 'pushAttentionProjection',
    });
  }

  // Wave 17: ingest path updates the ambient badge cache so the poll route
  // serves a cached cell (at most one short-lived bridge process per interval).
  let badge_cache = null;
  if (req.skip_badge_cache !== true) {
    try {
      badge_cache = refreshBadgeCacheAfterAttentionPush({
        home,
        justPushed: payload,
      });
    } catch {
      badge_cache = { ok: false, reason: 'badge_cache_refresh_failed' };
    }
  }

  return Object.freeze({
    ok: true,
    pushed: true,
    key,
    path: cellPath,
    cell: payload,
    bridge: 'pushAttentionProjection',
    index_walks_roots: false,
    atomic_write: 'writeFileAtomicSync',
    lock: 'withFileLock',
    badge_cache,
  });
}

/**
 * Read a pushed attention cell from the index (no project root walk).
 * @param {{ project_id?: string|null, project_path?: string|null, home?: string, paths?: object, env?: object }} req
 */
export function readAttentionFromIndex(req = {}) {
  const key = attentionIndexKey(req);
  if (!key) {
    return { ok: false, exists: false, cell: null, reason: 'no_key' };
  }
  let paths;
  try {
    paths = req.paths ?? indexPathsFrom({ home: req.home, env: req.env });
  } catch (e) {
    return { ok: false, exists: false, cell: null, reason: String(e?.message ?? e) };
  }
  const home = paths?.home ?? req.home;
  if (!home) return { ok: false, exists: false, cell: null, reason: 'home_unresolved' };
  const cellPath = attentionIndexCellPath(home, key);
  try {
    if (!fs.existsSync(cellPath)) return { ok: true, exists: false, cell: null, path: cellPath };
    const cell = JSON.parse(fs.readFileSync(cellPath, 'utf8'));
    return { ok: true, exists: true, cell, path: cellPath, index_walks_roots: false };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      cell: null,
      path: cellPath,
      reason: String(e?.message ?? e),
    };
  }
}

// -- ack-latency health ----------------------------------------------------------

/**
 * Whole days between two instants, floored and never negative.
 *
 * Clock skew is answered with zero rather than with a negative age: an intent whose recorded
 * wall clock is in the future is a clock problem, and reporting it as "-3 days degraded"
 * would turn a clock problem into a durability report nobody can read. Nothing is ORDERED by
 * this value - it is only ever a rendering (NG-4).
 *
 * @param {string|number|Date} from @param {number} nowMs @returns {number}
 */
export function daysBetween(from, nowMs) {
  const at = from instanceof Date ? from.getTime() : Date.parse(String(from));
  if (!Number.isFinite(at)) return 0;
  return Math.max(0, Math.floor((nowMs - at) / MS_PER_DAY));
}

/**
 * THE COMPOSITE. Ack latency, turned into criterion-level portfolio health.
 *
 * DEGRADED is reached by ONE condition, stated once: an unacknowledged intent older than the
 * threshold exists. Not "many" and not "the average" - the oldest single receipt that has not
 * left this disk is the thing at risk, and it is the thing the banner names.
 *
 * The count of receipts at risk is EVERY unacknowledged intent, not only the aged ones,
 * because that is the honest answer to "how much would I lose": a receipt written an hour ago
 * is as local-only as one written last week, it has simply not been local-only for long.
 *
 * @param {{events?: Array<object>, now?: number|Date, threshold_days?: number,
 *          last_export_days?: number|null, severity?: string}} [inputs]
 * @returns {Readonly<object>}
 */
export function durabilityHealth(inputs = {}) {
  const events = Array.isArray(inputs.events) ? inputs.events : [];
  const nowMs = new Date(inputs.now ?? Date.now()).getTime();
  const thresholdDays = Number.isFinite(inputs.threshold_days)
    ? Number(inputs.threshold_days)
    : ACK_THRESHOLD_DAYS;
  const ledger = intentLedger(events);

  const aged = [];
  let oldestDays = 0;
  // The instant the degradation STARTED: the wall clock of the oldest intent that is both
  // unacknowledged and past the threshold. It is kept in milliseconds rather than in floored
  // days because W16 compares an export against it, and a bundle taken six hours after the
  // degradation began covers it - a comparison in whole days would call that a tie.
  let degradedSinceMs = null;
  for (const intent of ledger.unacknowledged) {
    const age = daysBetween(intent.written_at, nowMs);
    if (age > oldestDays) oldestDays = age;
    if (age >= thresholdDays) {
      aged.push(Object.freeze({ ...intent, age_days: age }));
      const at = Date.parse(String(intent.written_at));
      if (Number.isFinite(at) && (degradedSinceMs === null || at < degradedSinceMs)) {
        degradedSinceMs = at;
      }
    }
  }

  const atRisk = ledger.unacknowledged.length;
  const degraded = aged.length > 0;

  // W16. How old the newest off-box copy is, read from the log's own bundle-exported events.
  // A caller may still state `last_export_days` (the surfaces' injection point, and what the
  // W15 tests pass), but nothing has to: the fact lives in the store it describes.
  const recency = exportRecency({ events, now: nowMs, degraded_since: degradedSinceMs });
  const injected = Number.isFinite(inputs.last_export_days) ? Number(inputs.last_export_days) : null;
  const lastExportDays = injected === null ? recency.last_export_days : injected;

  // A stated recency answers BOTH questions or neither. Rendering the caller's number while
  // escalating on the log's would put two different "last export" facts on one banner, which
  // is the sort of disagreement an operator has no way to notice.
  const covers = injected === null
    ? recency.covers
    : (degradedSinceMs === null ? null : nowMs - injected * MS_PER_DAY > degradedSinceMs);

  // THE ESCALATION, stated once. A portfolio that is DEGRADED and has no bundle newer than the
  // degradation start is the case where local disk is the only copy AND the only copy predates
  // the problem. That is not a notice, and it is not a warning that grows with age - it is
  // already the worst rung, so it is asked for outright. renderDegraded only ever RAISES a
  // severity, so this can never quieten a banner that age has already made louder.
  const escalate = degraded && covers !== true;

  // Per project, in id order, so a surface can render a stable list without sorting again.
  const perProject = Object.keys(ledger.per_project).sort().map((id) => {
    const entry = ledger.per_project[id];
    const oldest = entry.oldest_unacked;
    const age = oldest === null ? 0 : daysBetween(oldest.written_at, nowMs);
    return Object.freeze({
      project_id: id,
      emitted_seq: entry.emitted_seq,
      ack_seq: entry.ack_seq,
      unacknowledged: entry.unacknowledged,
      oldest_unacked_days: age,
      // The phrase, per project, so the stand-up and the High Seat cannot word it apart.
      rendering: entry.unacknowledged > 0 ? NOT_YET_COMMITTED : null,
    });
  });

  const banner = degraded
    ? renderDegraded({
      days_degraded: oldestDays,
      receipts_at_risk: atRisk,
      last_export_days: lastExportDays,
      severity: escalate ? DEGRADED_SEVERITY.CRITICAL : inputs.severity,
    })
    : null;

  return Object.freeze({
    version: ANCHOR_CONTRACT_VERSION,
    // DEGRADED is the composite; a portfolio whose intents are all acknowledged reads as the
    // integrity code for a store with nothing wrong with it, which is what it is.
    status: degraded
      ? assertStatusCode(COMPOSITE.DEGRADED, 'durability health')
      : assertStatusCode(INTEGRITY.OK, 'durability health'),
    degraded,
    threshold_days: thresholdDays,
    days_degraded: degraded ? oldestDays : 0,
    degraded_since: degradedSinceMs === null ? null : new Date(degradedSinceMs).toISOString(),
    receipts_at_risk: atRisk,
    severity: degraded ? (banner?.severity ?? degradedSeverityFor(oldestDays)) : null,
    // ONE banner. Not one per intent, not one per project.
    banner,
    banner_count: degraded ? 1 : 0,
    // Export recency is reported whether or not the portfolio is DEGRADED, and 'never' is
    // reported as loudly as a number: a portfolio nobody has ever exported is the one whose
    // silence is worth the most, and a field that only appeared once things were already bad
    // would be missing from every screen an operator reads while they are still fine.
    last_export_days: lastExportDays,
    last_export_ever: recency.ever,
    export_recency: recency,
    export_covers_degradation: degraded ? covers === true : null,
    escalated_for_export: escalate,
    aged_unacked: Object.freeze(aged),
    unacknowledged: ledger.unacknowledged,
    acknowledged: ledger.acknowledged,
    disagreements: ledger.disagreements,
    orphan_acks: ledger.orphan_acks,
    per_project: Object.freeze(perProject),
    watermark: ackWatermark(events),
    // The other side is not in this repository, and every surface says so.
    c7b: C7B_STATUS,
  });
}

/**
 * Read the log and answer the durability question, in one call, for the surfaces.
 *
 * An index that will not open is reported UNANSWERED, never healthy. "We could not check" and
 * "there is nothing wrong" are the two facts a health surface must never merge, and a
 * portfolio that renders as fine because its own index is unreadable is the exact silence
 * this criterion exists to break.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number|Date,
 *          threshold_days?: number, last_export_days?: number|null, boundMs?: number,
 *          staleMs?: number, quarantine?: boolean, lockOpts?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function readDurabilityHealth(opts = {}) {
  const read = openIndexForRead(opts);
  if (read.ok !== true) {
    return Object.freeze({
      version: ANCHOR_CONTRACT_VERSION,
      ok: false,
      status: assertStatusCode(FRESHNESS.UNKNOWN, 'durability health unreadable'),
      degraded: false,
      answered: false,
      outcome: anchorOutcome(ANCHOR_CODE.INDEX_UNREADABLE, {
        reason: read.text ? read.text : String(read.code),
      }, { appended: false }),
      banner: null,
      banner_count: 0,
      per_project: Object.freeze([]),
      c7b: C7B_STATUS,
    });
  }
  const health = durabilityHealth({ ...opts, events: read.events ?? [] });
  return Object.freeze({ ...health, ok: true, answered: true, head_seq: read.head_seq ?? 0 });
}

// -- the one rendering every surface uses ---------------------------------------

/**
 * The durability block a surface embeds. ONE banner, the per-project 'not yet committed'
 * lines, and C7b's open status - computed once here so the stand-up and the High Seat cannot
 * disagree about what the operator's durability looks like.
 *
 * Unacknowledged intents are NEVER hidden. A quiet portfolio still renders the block with
 * `present: false` and a line saying every receipt is acknowledged, because "no banner" and
 * "nobody checked" look identical when the block is simply absent.
 *
 * @param {Readonly<object>} health durabilityHealth() or readDurabilityHealth() output
 * @returns {Readonly<object>}
 */
export function renderDurabilityBlock(health = /** @type {any} */ ({})) {
  const answered = health.answered !== false;
  const perProject = Array.isArray(health.per_project) ? health.per_project : [];
  const pending = perProject.filter((p) => p.unacknowledged > 0);

  if (!answered) {
    return Object.freeze({
      block: 'durability',
      present: true,
      answered: false,
      status: health.status ?? assertStatusCode(FRESHNESS.UNKNOWN, 'durability block'),
      severity: DEGRADED_SEVERITY.WARNING,
      banner: health.outcome?.text ?? '',
      banner_count: 1,
      not_yet_committed: Object.freeze([]),
      receipts_at_risk: null,
      // Unanswered, not 'never': the index could not be read, so this surface does not know
      // when the last export was, and saying 'never' would be inventing the worst answer.
      last_export_days: null,
      last_export_line: null,
      c7b: C7B_STATUS,
    });
  }

  return Object.freeze({
    block: 'durability',
    present: true,
    answered: true,
    status: health.status,
    degraded: health.degraded === true,
    severity: health.severity ?? null,
    // ONE line, or none. The count is asserted by the test so "one banner" stays a property
    // rather than a habit.
    banner: health.banner?.text ?? null,
    banner_count: health.banner_count ?? 0,
    days_degraded: health.days_degraded ?? 0,
    receipts_at_risk: health.receipts_at_risk ?? 0,
    // W16, on every surface and in both states: the age of the off-box copy, in the same
    // words the banner uses, so a screen showing a healthy portfolio still shows an operator
    // that nothing has left this machine in a fortnight.
    last_export_days: health.last_export_days ?? null,
    last_export_line: health.export_recency?.text ?? null,
    export_covers_degradation: health.export_covers_degradation ?? null,
    // Never hidden: every project with work that has not left this disk is named, with the
    // one phrase both surfaces use.
    not_yet_committed: Object.freeze(pending.map((p) => Object.freeze({
      project_id: p.project_id,
      unacknowledged: p.unacknowledged,
      oldest_unacked_days: p.oldest_unacked_days,
      text:
        `${p.project_id}: ${NOT_YET_COMMITTED} - ${p.unacknowledged} receipt`
        + `${p.unacknowledged === 1 ? '' : 's'} waiting, oldest ${p.oldest_unacked_days} day`
        + `${p.oldest_unacked_days === 1 ? '' : 's'}.`,
    }))),
    all_acknowledged: pending.length === 0,
    quiet_text: pending.length === 0
      ? 'every commit-intent this log carries has been acknowledged.'
      : null,
    c7b: C7B_STATUS,
  });
}

/**
 * The durability block for a surface that has an index home to read. Surfaces call THIS, so
 * neither of them has to know how the log is opened.
 *
 * A surface given nothing to read gets the quiet block rather than an error: the stand-up
 * runs in projects that were never registered, and a view model that threw there would make
 * durability reporting a reason the screen does not render.
 *
 * @param {{events?: Array<object>|null, health?: object|null, home?: string, paths?: object,
 *          env?: object, fsx?: object, now?: number|Date, threshold_days?: number,
 *          last_export_days?: number|null}} [opts]
 * @returns {Readonly<object>}
 */
export function durabilityFor(opts = {}) {
  if (opts.health) return renderDurabilityBlock(opts.health);
  if (Array.isArray(opts.events)) return renderDurabilityBlock(durabilityHealth(opts));
  if (opts.home === undefined && opts.paths === undefined && opts.env === undefined) {
    return renderDurabilityBlock(durabilityHealth({ ...opts, events: [] }));
  }
  return renderDurabilityBlock(readDurabilityHealth(opts));
}

/** The schema id both repositories stamp their shared fixtures with. */
export const FIXTURE_MANIFEST_SCHEMA = 'anchor-contract-fixtures-v1';

/** Where the shared fixture set lives, repo-relative and POSIX - never a host path. */
export const FIXTURE_DIR = 'fixtures/anchor-contract';

/**
 * What the two sides owe each other, in one value.
 *
 * The engine's side is testable here and is green. Anchor's side is not in this repository,
 * which is why the fixture set is shared rather than duplicated: the same bytes that prove
 * the engine accepts an acknowledgement are the bytes Anchor must prove it can produce.
 */
export const CONTRACT_OBLIGATIONS = Object.freeze({
  engine_must:
    `emit one ${COMMIT_INTENT_SCHEMA} per durable project-state write, accept every valid `
    + `${COMMIT_ACK_SCHEMA} in the shared fixture set, refuse every invalid one by named row, `
    + 'and invoke no durability tool of its own',
  anchor_must:
    `acknowledge every ${COMMIT_INTENT_SCHEMA} in the shared fixture set with a `
    + `${COMMIT_ACK_SCHEMA} carrying the intent's exact hash`,
});

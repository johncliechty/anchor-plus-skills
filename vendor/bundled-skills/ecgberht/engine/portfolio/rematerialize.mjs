/**
 * W13 - the D-3 re-materializer: what keeps the tail merge bounded.
 *
 * WHY THIS EXISTS AT ALL. D-3 answers "is a receipt written one second ago findable?" with
 * yes, by merging the log's events after `freshness.head_seq` into the snapshot body at query
 * time. That answer is only affordable while the tail is SHORT. Left alone the tail grows for
 * as long as nobody runs `steward rebuild`, and the query surface's cost grows with it - which
 * is how a design that is correct on day one becomes a design nobody can query on day four
 * hundred. So D-3 pairs the merge with a bound: past `caps.tail_events` the snapshot is
 * recomputed and atomically replaced, and the merge cost returns to where it started. That
 * pairing IS the snapshot-refresh contract round 1 found undefined.
 *
 * WHAT IT FOLDS, AND WHY IT IS NOT A REBUILD. `steward rebuild` consumes input set I - the log
 * PLUS every live registered root, discovered through inventory-v1. This verb consumes the log
 * and the previous body, and it opens NO project root. That is not a shortcut, it is the
 * constraint: re-materialization is triggered BY a query, and C8 says the query path opens no
 * root. A re-materializer that walked the portfolio would put a full walk behind an operator's
 * `steward query`, which is exactly the no-walk property the wave exists to establish.
 *
 * SO THE BODY IS FOLDED, NOT RECOMPUTED - and the difference matters in one direction only:
 *
 *   - rows the LOG carries are folded in, replacing the body's row for the same identity;
 *   - rows the BODY carries and the log does not are KEPT. Those exist: the W8 crash window
 *     leaves a file durable on disk with no DERIVED event, and the rebuilder derives a row for
 *     it with a null seq. A re-materialization that dropped them would shrink the portfolio to
 *     make a merge cheaper, which is the silent shrink the North Star forbids, arriving through
 *     the one door nobody is watching.
 *
 * Everything else in the body - the unparseable, unclassified, hazard, conflict, refused,
 * retained and unknown lists - is the last WALK's findings. The log tail says nothing about any
 * of them, so they are carried forward verbatim rather than recomputed from information this
 * verb does not have. `steward rebuild` is what refreshes those, and it remains the only thing
 * that can.
 *
 * THE FRESHNESS BLOCK IS PRESERVED, NOT REFILLED. presence and freshness are answers about the
 * filesystem, and this verb did not look at the filesystem. It advances `head_seq` and
 * `head_sha256` (facts about the log, which it did read) and stamps `computed_at`; every
 * per-project entry is carried through untouched, and no entry is invented for a project that
 * no rebuild has ever observed. A per-project entry minted here would be a presence claim
 * nobody made - and it would change the freshness a query reports for a row, which is precisely
 * the thing that must NOT change across a re-materialization.
 *
 * Stdlib only.
 */

import {
  ORDERING_FIELD,
  indexPathsFrom,
  openIndexForRead,
  replayEvents,
  withPortfolioLock,
} from '../append-log.mjs';
import {
  SNAPSHOT_SCHEMA,
  serializeSnapshot,
  writeCanonicalSnapshot,
} from './canonical.mjs';
import { CAPS, capStatusFor } from './caps.mjs';
import { contentHashesFor } from './content-hash.mjs';
import { isDerivedEvent, rowIdentity } from './derive.mjs';
import { INVENTORY_VERSION } from './inventory.mjs';
import { REBUILD_VERSION, bodyRow, logHeadSha256 } from './rebuild.mjs';
import { materializeRegistry } from './registry.mjs';
import { emptyFreshnessBlock } from './snapshot-shape.mjs';

/** The re-materializer's frozen version. */
export const REMATERIALIZE_VERSION = 'rematerialize-v1';

/** The receipt this verb hands its caller. */
export const REMATERIALIZE_RECEIPT_SCHEMA = 'rematerialize-receipt-v1';

/** The cap whose ceiling triggers this verb, named so a caller cites it rather than 2000. */
export const TAIL_CAP_ID = 'tail_events';

/** Why a re-materialization ran. Closed: an unnamed trigger is one nobody can predict. */
export const REMATERIALIZE_TRIGGER = Object.freeze({
  TAIL_CAP: 'TAIL_EVENTS_PAST_CEILING',
  CALLER: 'CALLER_REQUESTED',
});

/**
 * The two list regions this fold recomputes rather than carries: membership comes from the
 * NATIVE events and the rows come from the tail merge. Every other list is the last WALK's
 * findings and is carried through verbatim.
 */
const FOLD_RECOMPUTED_KEYS = Object.freeze(['projects', 'rows', 'content_hashes']);

/**
 * The body keys a rebuilt body carries, so a folded body has the same shape as a rebuilt one.
 *
 * Derived from emptyBody() rather than retyped: several of these keys are the lowercase word
 * for a STATUS-v1 state ('unparseable', 'unclassified', 'unknown'), and a second hand-written
 * copy of one is exactly the drift status.mjs exists to prevent - the shape has one home, and
 * this reads it. (emptyBody is a hoisted function declaration, so calling it here is safe.)
 */
export const BODY_LIST_KEYS = Object.freeze(
  Object.entries(emptyBody())
    .filter(([key, value]) => Array.isArray(value) && !FOLD_RECOMPUTED_KEYS.includes(key))
    .map(([key]) => key),
);

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * The log's tail: every event after the sequence the snapshot was computed at.
 *
 * @param {ReadonlyArray<object>} events @param {number} headSeq
 * @returns {ReadonlyArray<object>} in seq order
 */
export function tailAfter(events, headSeq) {
  const after = Number(headSeq ?? 0);
  return Object.freeze(
    replayEvents(Array.isArray(events) ? events : [])
      .filter((event) => Number(event?.[ORDERING_FIELD]) > after),
  );
}

/**
 * Is the tail past its ceiling?
 *
 * Strictly past, not at: `caps.tail_events` is the longest tail the contract accepts, so the
 * event that makes it longer is the one that triggers the fold.
 *
 * @param {number} tailLength @returns {boolean}
 */
export function shouldRematerialize(tailLength) {
  return Number(tailLength ?? 0) > CAPS[TAIL_CAP_ID];
}

/**
 * Where the tail sits against its ceiling, including the 80% warning. One function, one rule -
 * caps.mjs owns the arithmetic and this module never restates the threshold.
 *
 * @param {number} tailLength @returns {Readonly<object>}
 */
export function tailCapStatus(tailLength) {
  return capStatusFor(TAIL_CAP_ID, Number(tailLength ?? 0));
}

/**
 * A body with every key a rebuilt body carries and nothing in it. The starting point when
 * there is no snapshot at all: the fold then materializes the whole log, which is honest -
 * nothing was walked, so every walk-derived list is genuinely empty rather than unknown.
 *
 * @returns {object}
 */
export function emptyBody() {
  return {
    version: REBUILD_VERSION,
    inventory_version: INVENTORY_VERSION,
    projects: [],
    rows: [],
    content_hashes: [],
    unparseable: [],
    unclassified: [],
    hazards: [],
    conflicts: [],
    refused: [],
    retained: [],
    unknown: [],
    forks: [],
    counts: {},
  };
}

/**
 * The projects region, materialized from NATIVE events - the same five fields, in the same
 * shape, the rebuilder writes. Membership is NATIVE in the log, so this is a recomputation
 * rather than a fold: the log is the whole truth about it.
 *
 * @param {ReadonlyArray<object>} events @returns {Array<object>}
 */
export function projectsFromEvents(events) {
  const view = materializeRegistry(events);
  return view.projects.map((project) => Object.freeze({
    project_id: project.project_id,
    registered_path: project.root,
    current_path: project.current_path,
    marker_sha256: project.marker_sha256,
    registered_seq: project.registered_seq,
  }));
}

/**
 * Fold the tail into the body.
 *
 * @param {object|null} base the previous body, or null when there is no snapshot
 * @param {ReadonlyArray<object>} events the whole log, in seq order
 * @param {{head_seq?: number}} [opts]
 * @returns {Readonly<{body: object, added: number, replaced: number, kept: number,
 *          folded: number}>}
 */
export function foldTailIntoBody(base, events, opts = {}) {
  const previous = isPlainObject(base) ? base : emptyBody();
  const headSeq = Number(opts.head_seq ?? 0);
  const tail = tailAfter(events, headSeq);

  /** @type {Map<string, object>} identity -> row */
  const byIdentity = new Map();
  for (const row of previous.rows ?? []) {
    if (!isPlainObject(row)) continue;
    byIdentity.set(rowIdentity(row), row);
  }
  const kept = byIdentity.size;

  let added = 0;
  let replaced = 0;
  for (const event of tail) {
    if (!isDerivedEvent(event)) continue;
    const key = rowIdentity(event);
    if (byIdentity.has(key)) replaced += 1;
    else added += 1;
    byIdentity.set(key, bodyRow(event, event[ORDERING_FIELD]));
  }

  const body = {
    version: previous.version ?? REBUILD_VERSION,
    inventory_version: previous.inventory_version ?? INVENTORY_VERSION,
    projects: projectsFromEvents(events),
    rows: [...byIdentity.values()],
  };
  // RECOMPUTED, not carried: the W14 content hash is a pure function of `rows`, and this fold
  // has just changed `rows`. Carrying the previous list forward would leave the snapshot
  // asserting a baseline for file versions it no longer describes - a verify that then
  // reported drift would be reporting the fold, not the disk.
  body.content_hashes = contentHashesFor(body.rows);
  for (const key of BODY_LIST_KEYS) {
    body[key] = Array.isArray(previous[key]) ? [...previous[key]] : [];
  }
  // The walk-derived counts are the last rebuild's and are carried through untouched; the two
  // this fold actually knows about are recomputed. A count recomputed from information this
  // verb does not have would be a number that looks measured and is not.
  body.counts = {
    ...(isPlainObject(previous.counts) ? previous.counts : {}),
    projects: body.projects.length,
    rows: body.rows.length,
  };

  return Object.freeze({
    body,
    added,
    replaced,
    kept,
    folded: added + replaced,
  });
}

/**
 * The freshness block after a fold: the log's two facts advanced, every per-project answer
 * preserved exactly as the last rebuild left it.
 *
 * @param {object|null} previous @param {{head_seq: number, head_sha256: string|null,
 *          computed_at: string}} parts
 * @returns {object}
 */
export function advancedFreshness(previous, parts) {
  const block = isPlainObject(previous) ? previous : {};
  return emptyFreshnessBlock({
    head_seq: Number(parts.head_seq ?? 0),
    head_sha256: parts.head_sha256 ?? null,
    computed_at: parts.computed_at,
    per_project: isPlainObject(block.per_project) ? { ...block.per_project } : {},
  });
}

/**
 * Re-materialize the snapshot from the log and the previous body, and replace it atomically.
 *
 * The caller may hand in a read it already performed (`events`, `body`, `freshness`,
 * `head_seq`) - which is what the query surface does, since it has just read the whole index
 * under the lock and a second read would be both slower and a different index.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number|Date,
 *          events?: ReadonlyArray<object>, body?: object|null, freshness?: object|null,
 *          head_seq?: number, trigger?: string, write?: boolean, boundMs?: number,
 *          staleMs?: number, lockOpts?: object, retries?: number, pid?: number,
 *          hostname?: string}} [opts]
 * @returns {Readonly<object>} the rematerialize-receipt-v1
 */
export function rematerializeIndex(opts = {}) {
  const paths = indexPathsFrom(opts);
  const trigger = opts.trigger ?? REMATERIALIZE_TRIGGER.CALLER;

  let events = opts.events ?? null;
  let base = opts.body ?? null;
  let freshness = opts.freshness ?? null;
  let headSeq = opts.head_seq;

  if (events === null) {
    const read = openIndexForRead({ ...opts, paths });
    if (read.ok !== true) {
      return Object.freeze({
        ok: false,
        schema: REMATERIALIZE_RECEIPT_SCHEMA,
        version: REMATERIALIZE_VERSION,
        trigger,
        home: paths.home,
        snapshot: paths.snapshot,
        outcome: read,
        body: null,
        freshness: null,
        write: null,
        fold: null,
      });
    }
    events = read.events;
    const snapshot = isPlainObject(read.snapshot_value) ? read.snapshot_value : null;
    base = snapshot === null ? null : snapshot.body ?? null;
    freshness = snapshot === null ? null : snapshot.freshness ?? null;
    if (headSeq === undefined) {
      headSeq = Number(isPlainObject(freshness) ? freshness.head_seq ?? 0 : 0);
    }
  }
  if (headSeq === undefined) {
    headSeq = Number(isPlainObject(freshness) ? freshness.head_seq ?? 0 : 0);
  }

  const ordered = replayEvents(Array.isArray(events) ? events : []);
  const tail = tailAfter(ordered, headSeq);
  const fold = foldTailIntoBody(base, ordered, { head_seq: headSeq });
  const logHead = ordered.length === 0
    ? 0
    : Number(ordered[ordered.length - 1][ORDERING_FIELD]);

  const nextFreshness = advancedFreshness(freshness, {
    head_seq: logHead,
    head_sha256: logHeadSha256(ordered),
    computed_at: new Date(opts.now ?? Date.now()).toISOString(),
  });

  const canonical = serializeSnapshot(
    { schema: SNAPSHOT_SCHEMA, body: fold.body, freshness: nextFreshness },
    opts,
  );

  let write = null;
  if (opts.write !== false) {
    write = withPortfolioLock(
      paths,
      () => writeCanonicalSnapshot(
        paths.snapshot,
        { schema: SNAPSHOT_SCHEMA, body: fold.body, freshness: nextFreshness },
        {
          fsx: opts.fsx,
          seq: logHead,
          pid: opts.pid,
          retries: opts.retries,
          hostname: opts.hostname,
        },
      ),
      { boundMs: opts.boundMs, staleMs: opts.staleMs, lockOpts: opts.lockOpts },
    );
  }

  return Object.freeze({
    ok: write === null ? true : write.ok === true,
    schema: REMATERIALIZE_RECEIPT_SCHEMA,
    version: REMATERIALIZE_VERSION,
    trigger,
    home: paths.home,
    snapshot: paths.snapshot,
    outcome: null,
    body: fold.body,
    freshness: nextFreshness,
    canonical,
    fold: Object.freeze({
      from_head_seq: Number(headSeq),
      to_head_seq: logHead,
      tail_events: tail.length,
      cap: tailCapStatus(tail.length),
      rows_added: fold.added,
      rows_replaced: fold.replaced,
      rows_kept: fold.kept,
      rows_total: fold.body.rows.length,
    }),
    write,
  });
}

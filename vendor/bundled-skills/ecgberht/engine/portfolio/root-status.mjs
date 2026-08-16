/**
 * W11 - the loud unknown: the root-status classifier and the DERIVED-retention contract.
 *
 * WHAT THIS MODULE IS FOR. The North Star's last clause is the one a portfolio index normally
 * fails silently: "a project the steward has lost track of reports itself loudly as
 * unknown/root-absent instead of silently shrinking the portfolio". Every index that has ever
 * lost a project lost it the same way - the root stopped answering, the walk found nothing
 * there, and the rebuild wrote a smaller portfolio with nothing anywhere saying a project had
 * gone. The count fell by one and no line of output was wrong.
 *
 * So this module owns three things, and refuses to own a fourth:
 *
 *   1. THE CLASSIFICATION. ABSENT vs UNREACHABLE, as distinct STATUS-v1 presence codes with
 *      separate renderings. ABSENT is exactly one situation: ENOENT on the root while its
 *      parent is readable - the steward LOOKED and the directory is not there. Everything
 *      else is UNREACHABLE - a denied ACL, a busy handle, a OneDrive placeholder that was
 *      never hydrated, a share whose host is not answering - because in every one of those
 *      the steward COULD NOT LOOK. Collapsing the two turns "your network is down" into
 *      "your project was deleted", which is the single most expensive lie this surface can
 *      tell: one of them is a cable and the other is a restore from backup.
 *
 *   2. THE LOUD-UNKNOWN ROW, reconstructed from NATIVE events ONLY. The registration event
 *      carries project_id, the registered path and the registration receipt id; the latest
 *      reconcile event carries the last-known path. That is the whole input. The row needs
 *      NOTHING from the missing root, which is the property that makes it possible at all -
 *      a row that had to read the marker to say a project exists could never be produced for
 *      the project whose marker is gone, and that is precisely the project the operator needs
 *      told about.
 *
 *   3. THE RETENTION CONTRACT. Absence changes presence and freshness, and NOTHING else. It
 *      never removes a row, never rebinds an id, and never reduces the retained DERIVED set
 *      for ANY class. `retentionSetOf` and `retentionEqual` state that as something countable
 *      per class - receipt AND instrument AND roadmap-event, class-symmetry legs 9 and 10 -
 *      rather than as a sentence, because "the rows are retained" is exactly the kind of claim
 *      that stays true for receipts and quietly stops being true for the other two.
 *
 * WHAT IT REFUSES TO OWN: the errno rule itself. W2's `classifyRootFailure` already decides
 * which errno means ABSENT, and a second copy here would be one rule and one hole - the two
 * would agree until the day somebody fixed a UNC edge case in one of them. This module CALLS
 * it and adds the two cases an errno cannot express: a stat that SUCCEEDS on a cloud
 * placeholder whose content was never hydrated, and a directory that stats fine and cannot be
 * listed.
 *
 * ON THOSE PLACEHOLDERS, HONESTLY. Node's `fs.Stats` does not surface Windows file attributes,
 * so this module cannot read the recall bits from the stdlib alone and does not pretend to:
 * `attributesOf` is an injection seam, the default reads an `attributes` field if the stat
 * object happens to carry one, and a host that supplies neither simply never reaches the
 * placeholder branch and falls through to the errno rule - which will report UNREACHABLE
 * anyway the moment the recall fails. The seam exists so the branch is testable and so a
 * later wave can fill it from a real attribute source without moving the rule.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import { DERIVABLE_CLASSES, isDerivableClass, rowIdentity } from './derive.mjs';
import { classifyRootFailure, openablePath } from './inventory.mjs';
import {
  COMPOSITE,
  FRESHNESS,
  PRESENCE,
  UNKNOWN_TOKEN,
  assertStatusCode,
  isUnknownRow,
  renderUnknownRow,
} from './status.mjs';

/** The classifier's frozen version. Changing what ABSENT means is root-status-v2. */
export const ROOT_STATUS_VERSION = 'root-status-v1';

/** The loud-unknown row's schema id. */
export const UNKNOWN_ROW_SCHEMA = 'unknown-row-v1';

/**
 * The named reasons this module adds on top of W2's errno rule.
 *
 * They are reasons, not statuses: the STATUS-v1 answer is always one of PRESENCE's three
 * members, and the reason says which road led there so an operator can act on it.
 */
export const ROOT_STATUS_REASON = Object.freeze({
  NOT_A_DIRECTORY: 'NOT_A_DIRECTORY',
  CLOUD_PLACEHOLDER: 'CLOUD_PLACEHOLDER_NOT_HYDRATED',
  LISTING_FAILED: 'LISTING_FAILED',
});

/**
 * The Windows file attributes that mean "these bytes are not here yet".
 *
 * Named with their full Win32 names on purpose: the bare word for the first of them is an
 * ad-hoc status synonym the W3 lint forbids on this surface, and rightly - a placeholder is
 * not a presence code, it is a reason a presence code came out UNREACHABLE.
 */
export const WIN32_FILE_ATTRIBUTE = Object.freeze({
  FILE_ATTRIBUTE_OFFLINE: 0x0000_1000,
  FILE_ATTRIBUTE_REPARSE_POINT: 0x0000_0400,
  FILE_ATTRIBUTE_RECALL_ON_OPEN: 0x0004_0000,
  FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: 0x0040_0000,
});

/** The attribute names whose presence makes a root UNREACHABLE rather than LIVE. */
export const PLACEHOLDER_ATTRIBUTES = Object.freeze([
  'FILE_ATTRIBUTE_OFFLINE',
  'FILE_ATTRIBUTE_RECALL_ON_OPEN',
  'FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS',
]);

/** The three above, OR-ed, so one test says "is this root a placeholder". */
export const PLACEHOLDER_ATTRIBUTE_MASK = PLACEHOLDER_ATTRIBUTES.reduce(
  (mask, name) => mask | WIN32_FILE_ATTRIBUTE[name],
  0,
);

/**
 * Errno codes that mean the far end did not answer.
 *
 * They are NOT a branch in the classifier - W2's rule already sends every non-ENOENT failure
 * to UNREACHABLE - they are here so the RENDERING can tell an operator whether to check a
 * cable or a permission, which is the difference between a five-minute fix and an afternoon.
 */
export const NETWORK_ERRNO = Object.freeze([
  'ECONNABORTED',
  'ECONNRESET',
  'EHOSTDOWN',
  'EHOSTUNREACH',
  'ENETDOWN',
  'ENETUNREACH',
  'ENODEV',
  'EREMOTEIO',
  'ETIMEDOUT',
]);

/** Errno codes a failed cloud recall surfaces as, including libuv's catch-all. */
export const CLOUD_ERRNO = Object.freeze(['EBUSY', 'EIO', UNKNOWN_TOKEN]);

/** Errno codes that mean the steward was refused rather than that nothing is there. */
export const DENIED_ERRNO = Object.freeze(['EACCES', 'EPERM']);

/** The loud-unknown row's CLOSED field set, in canonical order. */
export const UNKNOWN_ROW_FIELDS = Object.freeze([
  'schema',
  'project_id',
  'presence',
  'freshness',
  'rendering',
  'registered_path',
  'registration_receipt_id',
  'registered_seq',
  'last_known_path',
  'last_known_seq',
  'reason',
  'text',
]);

/** The refusals this module raises at a CALLER, not at an operator. */
export const ROOT_STATUS_REFUSAL = Object.freeze({
  NOT_A_PROJECT_ENTRY: 'ROOT_STATUS_NOT_A_PROJECT_ENTRY',
  ROOT_IS_LIVE: 'ROOT_STATUS_ROOT_IS_LIVE',
});

// -- placeholder attributes ----------------------------------------------------

/**
 * @param {unknown} mask a Win32 file-attribute bitmask
 * @returns {ReadonlyArray<string>} the placeholder attributes it carries, sorted
 */
export function placeholderAttributeNames(mask) {
  const bits = Number(mask);
  if (!Number.isFinite(bits) || bits <= 0) return Object.freeze([]);
  return Object.freeze(
    [...PLACEHOLDER_ATTRIBUTES].sort().filter((name) => (bits & WIN32_FILE_ATTRIBUTE[name]) !== 0),
  );
}

/** @param {unknown} mask @returns {boolean} true when the bytes are not locally present */
export function isPlaceholderAttributeMask(mask) {
  const bits = Number(mask);
  return Number.isFinite(bits) && (bits & PLACEHOLDER_ATTRIBUTE_MASK) !== 0;
}

/**
 * The default attribute source: whatever the stat object carries.
 *
 * Node's own `fs.Stats` carries nothing here and that is fine - see the header. Returning 0
 * means "no attribute evidence", which falls through to the errno rule rather than guessing.
 *
 * @param {string} _rootAbs @param {object|null} stat @returns {number}
 */
export function attributeMaskOf(_rootAbs, stat) {
  const raw = stat === null || stat === undefined ? 0 : Number(stat.attributes);
  return Number.isFinite(raw) ? raw : 0;
}

// -- the classification --------------------------------------------------------

/**
 * Build a frozen root-status verdict.
 *
 * Exported because the rebuilder sometimes learns a root is non-live from the WALK rather than
 * from a fresh probe (the root vanished between the two), and it must be able to express that
 * verdict in this module's shape instead of composing a second one of its own.
 *
 * @param {string} rootInput @param {string} presence @param {string|null} reason
 * @param {{errno?: string|null, attributes?: ReadonlyArray<string>}} [extra]
 * @returns {Readonly<object>}
 */
export function rootStatusOf(rootInput, presence, reason = null, extra = {}) {
  assertStatusCode(presence, 'rootStatusOf(presence)');
  const root = path.resolve(String(rootInput ?? ''));
  const live = presence === PRESENCE.LIVE;
  return Object.freeze({
    version: ROOT_STATUS_VERSION,
    root,
    presence,
    // The freshness half of the loud-unknown pair. A root nobody could read has rows nobody
    // re-verified, and saying anything other than UNKNOWN about them would be a guess.
    freshness: live ? FRESHNESS.FRESH : FRESHNESS.UNKNOWN,
    reason: reason === null || reason === undefined ? null : String(reason),
    live,
    absent: presence === PRESENCE.ABSENT,
    unreachable: presence === PRESENCE.UNREACHABLE,
    lost: !live,
    errno: extra.errno === undefined ? null : extra.errno,
    attributes: Object.freeze([...(extra.attributes ?? [])]),
  });
}

/**
 * Classify one registered root: LIVE, ABSENT, or UNREACHABLE.
 *
 * THE ORDER OF THE CHECKS IS THE CONTRACT, so it is stated rather than left to the reader:
 *
 *   stat fails            -> W2's errno rule decides (ENOENT + readable parent = ABSENT,
 *                            everything else = UNREACHABLE, any UNC failure = UNREACHABLE)
 *   stat succeeds, not a directory  -> UNREACHABLE. Something is there and it is not the root.
 *   placeholder attributes          -> UNREACHABLE. The name is present and the bytes are not.
 *   the directory cannot be listed  -> UNREACHABLE. A root the walk cannot enter is not live.
 *   otherwise                       -> LIVE.
 *
 * A root is never reported ABSENT because a LISTING failed: the directory demonstrably exists,
 * so "it is gone" would be false in the one direction that costs the operator a restore.
 *
 * @param {string} rootInput
 * @param {{fsx?: object, fs?: object, attributesOf?: Function, probeListing?: boolean}} [opts]
 * @returns {Readonly<object>}
 */
export function classifyRootStatus(rootInput, opts = {}) {
  const fsx = opts.fsx ?? opts.fs ?? fs;
  const statSync = fsx.statSync ?? fs.statSync;
  const readdirSync = fsx.readdirSync ?? fs.readdirSync;
  const attributesOf = typeof opts.attributesOf === 'function' ? opts.attributesOf : attributeMaskOf;
  const root = path.resolve(String(rootInput ?? ''));

  let stat;
  try {
    stat = statSync(openablePath(root));
  } catch (err) {
    // W2's rule, called rather than copied. ABSENT is ITS decision, made in one place.
    const verdict = classifyRootFailure(err, root, { statSync });
    return rootStatusOf(root, verdict.presence, verdict.reason, {
      errno: (err && err.code) || null,
    });
  }

  if (typeof stat?.isDirectory === 'function' && !stat.isDirectory()) {
    return rootStatusOf(root, PRESENCE.UNREACHABLE, ROOT_STATUS_REASON.NOT_A_DIRECTORY);
  }

  const attributes = placeholderAttributeNames(attributesOf(root, stat));
  if (attributes.length > 0) {
    return rootStatusOf(root, PRESENCE.UNREACHABLE, ROOT_STATUS_REASON.CLOUD_PLACEHOLDER, {
      attributes,
    });
  }

  if (opts.probeListing !== false) {
    try {
      readdirSync(openablePath(root));
    } catch (err) {
      const code = (err && err.code) || UNKNOWN_TOKEN;
      return rootStatusOf(root, PRESENCE.UNREACHABLE, `${ROOT_STATUS_REASON.LISTING_FAILED}_${code}`, {
        errno: code,
      });
    }
  }

  return rootStatusOf(root, PRESENCE.LIVE, null);
}

// -- the rendering, separate per presence --------------------------------------

/**
 * What an operator should DO about it, which is the half a status code cannot carry.
 *
 * The two sentences are deliberately different actions, not two wordings of one: an ABSENT
 * root is a move or a deletion and the answer is `reconcile --moved` or a restore; an
 * UNREACHABLE root is a cable, an ACL or an un-hydrated placeholder and the answer is to make
 * it readable and look again. A surface that printed one sentence for both would have merged
 * the two states again in the only place the operator actually reads.
 *
 * @param {Readonly<object>} status @returns {string}
 */
export function remedyFor(status) {
  if (status.presence === PRESENCE.ABSENT) {
    return (
      'The steward looked and the directory is not there. If you moved it, run '
      + '`steward reconcile --moved <old> <new>` to rebind the SAME project_id; if it was '
      + 'deleted, restore it. Nothing was removed from the portfolio and no id was reminted.'
    );
  }
  if (NETWORK_ERRNO.includes(String(status.errno))) {
    return (
      'The steward could not look: the host or share did not answer. Reconnect it and run '
      + '`steward verify`. This is NOT a deletion - no row was dropped and no binding changed.'
    );
  }
  if (
    status.reason === ROOT_STATUS_REASON.CLOUD_PLACEHOLDER
    || CLOUD_ERRNO.includes(String(status.errno))
  ) {
    const named = status.attributes ?? [];
    const which = named.length > 0 ? ` (${named.join(', ')})` : '';
    return (
      'The steward could not look: the root is a cloud placeholder whose contents were never '
      + `brought down to this machine${which}. Make the files locally available and run `
      + '`steward verify`. Its rows are retained meanwhile.'
    );
  }
  if (DENIED_ERRNO.includes(String(status.errno))) {
    return (
      'The steward could not look: the filesystem refused access to the root. Grant read '
      + 'access and run `steward verify`. Its rows are retained and its identity is unchanged.'
    );
  }
  return (
    'The steward could not look, and the cause is not a deletion. Make the root readable and '
    + 'run `steward verify`. Its rows are retained and its identity is unchanged.'
  );
}

/**
 * Render a non-live root as the operator reads it.
 *
 * The composite half is NOT re-decided here - `renderUnknownRow` in status.mjs owns what the
 * unknown row IS, and this function adds the reason and the remedy. Two surfaces that each
 * decided what unknown looks like is exactly how the honest signal rots back into prose.
 *
 * @param {Readonly<object>} status
 * @param {{project_id?: string|null, last_known_path?: string|null}} [parts]
 * @returns {Readonly<object>}
 */
export function renderRootStatus(status, parts = {}) {
  if (status.live === true) {
    throw new Error(
      `${ROOT_STATUS_REFUSAL.ROOT_IS_LIVE}: ${status.root} classified ${status.presence}; the `
      + 'unknown rendering is for a root the steward has lost track of, and rendering a live '
      + 'root as one would hide a project that is right where it should be.',
    );
  }
  const composite = renderUnknownRow({
    presence: status.presence,
    freshness: status.freshness,
    project_id: parts.project_id ?? null,
    last_known_path: parts.last_known_path ?? status.root,
  });
  const remedy = remedyFor(status);
  return Object.freeze({
    rendering: composite.rendering,
    presence: status.presence,
    freshness: status.freshness,
    project_id: composite.project_id,
    last_known_path: composite.last_known_path,
    reason: status.reason,
    remedy,
    // Reason and remedy both ride the text, so the two presences render as two different
    // sentences even where a caller prints nothing but `text`.
    text: `${composite.text} Cause: ${status.reason ?? status.presence}. ${remedy}`,
  });
}

// -- the loud-unknown row, from NATIVE events only ------------------------------

/**
 * The last path any NATIVE event named for this project.
 *
 * The registration event names the registered path; every reconcile event names the path the
 * project moved to. The LATEST reconcile therefore holds the last-known location, and where
 * there has never been one the registered path IS the last-known location.
 *
 * @param {Readonly<object>} project a registry-view entry (materialized from NATIVE events)
 * @returns {{path: string, seq: number, from: string}}
 */
export function lastKnownLocation(project) {
  const moves = Array.isArray(project?.moves) ? project.moves : [];
  const latest = moves.length > 0 ? moves[moves.length - 1] : null;
  if (latest !== null) {
    return {
      path: path.resolve(String(latest.to_path)),
      seq: Number(latest.seq),
      from: 'reconcile',
    };
  }
  return {
    path: path.resolve(String(project.root)),
    seq: Number(project.registered_seq),
    from: 'registration',
  };
}

/**
 * Reconstruct the explicit 'unknown' row for a project whose root is not live.
 *
 * NOTHING HERE TOUCHES A FILESYSTEM, and that is the deliverable rather than an optimization.
 * The inputs are a registry entry (which is itself a fold of NATIVE log events) and a
 * classification verdict. The row is therefore producible for exactly the project that can
 * supply nothing: the one whose root is gone.
 *
 * Note what is NOT on the row: `registered_at`. It is a clock, D-2 confines clocks to the
 * freshness block, and the W6 purity lint would refuse the body outright for carrying it.
 * The registration's position in the log's total order - `registered_seq` - says everything
 * about ordering that a timestamp would have, and it says it deterministically.
 *
 * @param {Readonly<object>} project a registry-view entry
 * @param {Readonly<object>} status a verdict from classifyRootStatus / rootStatusOf
 * @returns {Readonly<object>} the unknown-row-v1
 */
export function unknownRowFromNative(project, status) {
  if (project === null || typeof project !== 'object' || typeof project.project_id !== 'string') {
    throw new Error(
      `${ROOT_STATUS_REFUSAL.NOT_A_PROJECT_ENTRY}: the loud-unknown row is reconstructed from `
      + 'the NATIVE registration and reconcile events for one project; it was handed '
      + `${JSON.stringify(project)}.`,
    );
  }
  const lastKnown = lastKnownLocation(project);
  const rendered = renderRootStatus(status, {
    project_id: project.project_id,
    last_known_path: lastKnown.path,
  });
  return Object.freeze({
    schema: UNKNOWN_ROW_SCHEMA,
    project_id: project.project_id,
    presence: status.presence,
    freshness: status.freshness,
    rendering: rendered.rendering,
    registered_path: path.resolve(String(project.root)),
    registration_receipt_id: String(project.registration_receipt_id),
    registered_seq: Number(project.registered_seq),
    last_known_path: lastKnown.path,
    last_known_seq: lastKnown.seq,
    reason: status.reason,
    text: rendered.text,
  });
}

/**
 * @param {unknown} row
 * @returns {Readonly<{ok: boolean, problems: ReadonlyArray<string>}>}
 */
export function validateUnknownRow(row) {
  const problems = [];
  if (row === null || typeof row !== 'object') {
    return Object.freeze({ ok: false, problems: Object.freeze(['the row is not an object']) });
  }
  const keys = Object.keys(row).sort();
  const wanted = [...UNKNOWN_ROW_FIELDS].sort();
  if (keys.join(',') !== wanted.join(',')) {
    problems.push(`the field set is {${keys.join(',')}}; unknown-row-v1 is {${wanted.join(',')}}`);
  }
  if (row.schema !== UNKNOWN_ROW_SCHEMA) problems.push(`schema is ${JSON.stringify(row.schema)}`);
  if (!isUnknownRow(row)) {
    problems.push(
      `presence ${row.presence} with freshness ${row.freshness} is not the unknown row; it is `
      + `(${PRESENCE.ABSENT} or ${PRESENCE.UNREACHABLE}) with freshness ${FRESHNESS.UNKNOWN}`,
    );
  }
  if (row.rendering !== COMPOSITE.UNKNOWN_ROW) problems.push('the row does not render as the composite');
  if (typeof row.project_id !== 'string' || row.project_id === '') problems.push('project_id is absent');
  if (typeof row.last_known_path !== 'string' || row.last_known_path === '') {
    problems.push('last_known_path is absent - an unknown row that cannot say where to look is a shrug');
  }
  return Object.freeze({ ok: problems.length === 0, problems: Object.freeze(problems) });
}

/** @param {ReadonlyArray<object>} rows @returns {ReadonlyArray<object>} sorted by project_id */
export function sortUnknownRows(rows) {
  return Object.freeze(
    [...(rows ?? [])].sort((a, b) => (a.project_id < b.project_id ? -1 : a.project_id > b.project_id ? 1 : 0)),
  );
}

// -- freshness on replayed rows ------------------------------------------------

/**
 * The freshness a DERIVED row replayed from the log carries.
 *
 * It is UNKNOWN, and the reason is the same on both roads that reach here: nobody read the
 * bytes this pass. For a non-live root that is the plan's clause in full - the root could not
 * be opened, so every one of its rows is a memory rather than an observation. For a LIVE root
 * whose file was not discovered it is the same fact about one file. Calling it FRESH because
 * the log once said so would make a row that has not been checked since a machine ago
 * indistinguishable from one hashed a second ago.
 *
 * @param {string} presence the root's STATUS-v1 presence
 * @returns {string} a STATUS-v1 freshness code
 */
export function replayedRowFreshness(presence) {
  assertStatusCode(presence, 'replayedRowFreshness(presence)');
  return FRESHNESS.UNKNOWN;
}

// -- identity bindings are untouched by absence --------------------------------

/**
 * The identity bindings a registry view holds, as comparable data.
 *
 * "Absence never changes identity bindings" is only checkable if a binding is a value
 * something can hold on to across an operation, so this is the value: one entry per project,
 * naming the id, the path it is bound to, the path it was registered at, and the marker hash
 * the log recorded. A rebuild over a vanished root must produce this exact list again.
 *
 * @param {Readonly<object>|ReadonlyArray<object>} view a registry view, or its projects array
 * @returns {ReadonlyArray<Readonly<object>>} sorted by project_id
 */
export function bindingSnapshot(view) {
  // Either the view or its projects array, because the rebuild receipt hands out the array
  // and the registry hands out the view - and a helper that silently returned [] for one of
  // the two would make "the bindings are unchanged" pass by comparing nothing to nothing.
  const projects = Array.isArray(view)
    ? view
    : (Array.isArray(view?.projects) ? view.projects : []);
  return Object.freeze(
    projects
      .map((p) => Object.freeze({
        project_id: p.project_id,
        bound_path: path.resolve(String(p.current_path)),
        registered_path: path.resolve(String(p.root)),
        registration_receipt_id: String(p.registration_receipt_id),
        marker_sha256: String(p.marker_sha256),
        registered_seq: Number(p.registered_seq),
      }))
      .sort((a, b) => (a.project_id < b.project_id ? -1 : a.project_id > b.project_id ? 1 : 0)),
  );
}

/**
 * @param {ReadonlyArray<object>} before @param {ReadonlyArray<object>} after
 * @returns {Readonly<{equal: boolean, changed: ReadonlyArray<string>, text: string}>}
 */
export function bindingsEqual(before, after) {
  const left = new Map((before ?? []).map((b) => [b.project_id, JSON.stringify(b)]));
  const right = new Map((after ?? []).map((b) => [b.project_id, JSON.stringify(b)]));
  const changed = [];
  for (const [id, text] of left) {
    if (!right.has(id)) changed.push(`${id} no longer binds`);
    else if (right.get(id) !== text) changed.push(`${id} binds differently`);
  }
  for (const id of right.keys()) if (!left.has(id)) changed.push(`${id} appeared`);
  changed.sort();
  return Object.freeze({
    equal: changed.length === 0,
    changed: Object.freeze(changed),
    text:
      changed.length === 0
        ? 'every identity binding is unchanged'
        : `identity bindings changed: ${changed.join('; ')}`,
  });
}

// -- the DERIVED retention set, per class --------------------------------------

/**
 * The classes retention is counted over. Read from derive.mjs's derivable set rather than
 * typed, so a fourth class is retained by construction instead of by somebody remembering.
 */
const RETENTION_CLASSES = Object.freeze([...DERIVABLE_CLASSES].sort());

/**
 * The retained DERIVED set of a body's rows, keyed by row identity and split PER CLASS.
 *
 * Per class, always, including the classes that came out empty: legs 9 and 10 of the
 * class-symmetry matrix are exactly the case where receipts survive an absent root and
 * instruments or roadmap events quietly do not. An aggregate count would stay reassuringly
 * large while one whole column went to zero.
 *
 * @param {ReadonlyArray<object>} rows body rows (or log DERIVED events)
 * @param {{project_id?: string}} [opts]
 * @returns {Readonly<{all: ReadonlyArray<string>, by_class: Readonly<Record<string, ReadonlyArray<string>>>, size: number}>}
 */
export function retentionSetOf(rows, opts = {}) {
  const wanted = opts.project_id === undefined || opts.project_id === null ? null : String(opts.project_id);
  const byClass = new Map(RETENTION_CLASSES.map((c) => [c, new Set()]));
  const all = new Set();

  for (const row of rows ?? []) {
    if (row === null || typeof row !== 'object') continue;
    if (!isDerivableClass(row.class)) continue;
    if (wanted !== null && String(row.project_id) !== wanted) continue;
    const key = rowIdentity(row);
    all.add(key);
    if (!byClass.has(row.class)) byClass.set(row.class, new Set());
    byClass.get(row.class).add(key);
  }

  const out = {};
  for (const [className, keys] of [...byClass.entries()].sort()) {
    out[className] = Object.freeze([...keys].sort());
  }
  return Object.freeze({
    all: Object.freeze([...all].sort()),
    by_class: Object.freeze(out),
    size: all.size,
  });
}

/**
 * Set-equality between two retention sets, reported per class.
 *
 * `missing` is the one that matters and is named first everywhere it is reported: a key that
 * was retained before and is not retained now IS the silent shrink, whatever the totals say.
 *
 * @param {Readonly<object>} before @param {Readonly<object>} after
 * @returns {Readonly<object>}
 */
export function retentionEqual(before, after) {
  const classes = [...new Set([
    ...Object.keys(before?.by_class ?? {}),
    ...Object.keys(after?.by_class ?? {}),
  ])].sort();

  const byClass = {};
  const missing = [];
  const added = [];

  for (const className of classes) {
    const left = new Set(before?.by_class?.[className] ?? []);
    const right = new Set(after?.by_class?.[className] ?? []);
    const gone = [...left].filter((k) => !right.has(k)).sort();
    const extra = [...right].filter((k) => !left.has(k)).sort();
    missing.push(...gone);
    added.push(...extra);
    byClass[className] = Object.freeze({
      equal: gone.length === 0 && extra.length === 0,
      retained: left.size,
      now: right.size,
      missing: Object.freeze(gone),
      added: Object.freeze(extra),
    });
  }

  missing.sort();
  added.sort();
  return Object.freeze({
    equal: missing.length === 0 && added.length === 0,
    missing: Object.freeze(missing),
    added: Object.freeze(added),
    by_class: Object.freeze(byClass),
    text:
      missing.length === 0 && added.length === 0
        ? `the retained DERIVED set is set-equal across ${classes.length} class(es)`
        : `retained DERIVED set changed: ${missing.length} row(s) no longer retained `
          + `(${missing.slice(0, 4).join(', ')}), ${added.length} added`,
  });
}

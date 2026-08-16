/**
 * W2 - inventory-v1 as executable discovery code, plus the NG-2 deterministic walk.
 *
 * WHY THIS FILE EXISTS. "Per-project files" is not a category. Stage 1 froze a CLOSED
 * table naming every file the portfolio index may ever ingest, and until that table is
 * code it is decoration: the rebuild equation's input set I is only "closed" if something
 * can be asked, of an arbitrary path, which class it is - and can answer "none of them"
 * without the file quietly disappearing from the accounting.
 *
 * Two properties are load-bearing here and are the whole reason the walk is hand-written
 * rather than a three-line readdir recursion:
 *
 *  1. TOTALITY. Every file under a registered root leaves the walk in exactly one of
 *     three states: it matched a discovery path (and is then parsed or UNPARSEABLE), or
 *     it matched none (and is then UNCLASSIFIED, carrying its path). Nothing is silently
 *     ingested and nothing is silently ignored. parsed + unparseable + unclassified ==
 *     discovered is an equation the census asserts, not a hope.
 *
 *  2. DETERMINISM (NG-2). "Delete-and-rebuild is deterministic" is a claim about the
 *     WALK before it is a claim about the serializer. So: entries are ordered by an
 *     explicitly locale-free comparator (String#toLowerCase, never toLocaleLowerCase,
 *     never localeCompare - the last one genuinely reorders under a different ICU locale);
 *     reparse points are recorded and NOT followed; re-entering a directory already
 *     visited is refused on its file index; an over-length path is opened through the
 *     extended-length prefix rather than throwing; and a case-colliding pair is named on
 *     BOTH paths. Every one of those resolves to a named hazard code. None of them
 *     resolves to an exception, and none to a silent skip.
 *
 * The extension gate is the third property and the one that is easiest to lose: adding a
 * class is a RATIFICATION act, not a code edit. INVENTORY_V1 is frozen and extendInventory
 * refuses without a ratification record, so a future maintainer who "just adds a row"
 * fails loudly instead of quietly widening the closed set the rebuild equation rests on.
 *
 * Stdlib only. No runtime dependencies.
 */

import fs from 'node:fs';
import path from 'node:path';

import { isValidUtf8, scanBytesForMojibake } from '../encoding.mjs';
// W3: STATUS-v1 is the single enum module. Every status literal this file used to declare
// for itself now READS from there, so test/w49-status-enum-lint.test.mjs can forbid the
// literals outside status.mjs without carving out an exception for the module that walks.
import {
  INTEGRITY,
  PATH_HAZARD,
  PRESENCE as STATUS_PRESENCE,
  UNKNOWN_TOKEN,
} from './status.mjs';

/** The frozen table's version. Extending it means inventory-v2 and a ratification entry. */
export const INVENTORY_VERSION = 'inventory-v1';

/** The four ingestable classes, in their frozen order. */
export const CLASS = Object.freeze({
  RECEIPT: 'receipt',
  INSTRUMENT: 'instrument',
  ROADMAP_EVENT: 'roadmap-event',
  IDENTITY_MARKER: 'identity-marker',
});

/** @type {ReadonlyArray<string>} */
export const INVENTORY_CLASSES = Object.freeze([
  CLASS.RECEIPT,
  CLASS.INSTRUMENT,
  CLASS.ROADMAP_EVENT,
  CLASS.IDENTITY_MARKER,
]);

/**
 * The pseudo-class every file that matched no discovery path lands in. It is a BUCKET,
 * not a hole: an UNCLASSIFIED row carries its path and is counted in the totality
 * equation exactly like a parsed one.
 */
export const UNCLASSIFIED = INTEGRITY.UNCLASSIFIED;

/** Where the table was frozen. Cited by every entry so the provenance cannot be lost. */
const RATIFIED_BY = 'stage1 MASTER-PLAN.md, section "Closed Inventory (inventory-v1, frozen)"';

/**
 * inventory-v1, frozen. `spec` is the table's own wording; everything else is that
 * wording made executable. `depth: 2` is deliberate - the frozen path is `<root>/receipts/
 * *.json`, one level, so a file at `<root>/receipts/2026/a.json` is UNCLASSIFIED rather
 * than silently ingested by a recursive glob nobody ratified.
 */
export const INVENTORY_V1 = Object.freeze([
  Object.freeze({
    class: CLASS.RECEIPT,
    spec: '<root>/receipts/*.json',
    dir: 'receipts',
    file: null,
    extension: '.json',
    depth: 2,
    framing: 'json',
    tag: 'DERIVED',
    id_field: 'receipt_id',
    fields: Object.freeze(['receipt_id', 'kind', 'ts']),
    row_shape: "{t:'receipt', project_id, receipt_id, kind, ts, path, hash}",
    inventory_version: INVENTORY_VERSION,
    ratified_by: RATIFIED_BY,
  }),
  Object.freeze({
    class: CLASS.INSTRUMENT,
    spec: '<root>/instruments/*.json',
    dir: 'instruments',
    file: null,
    extension: '.json',
    depth: 2,
    framing: 'json',
    tag: 'DERIVED',
    id_field: 'instrument_id',
    fields: Object.freeze(['instrument_id', 'name', 'ts']),
    row_shape: "{t:'instrument', project_id, instrument_id, name, ts, path, hash}",
    inventory_version: INVENTORY_VERSION,
    ratified_by: RATIFIED_BY,
  }),
  Object.freeze({
    class: CLASS.ROADMAP_EVENT,
    spec: '<root>/roadmap/*.jsonl (one event per line)',
    dir: 'roadmap',
    file: null,
    extension: '.jsonl',
    depth: 2,
    framing: 'jsonl',
    tag: 'DERIVED',
    id_field: 'event_id',
    fields: Object.freeze(['event_id', 'phase', 'ts']),
    row_shape: "{t:'roadmap-event', project_id, event_id, phase, ts, path, hash}",
    inventory_version: INVENTORY_VERSION,
    ratified_by: RATIFIED_BY,
  }),
  Object.freeze({
    class: CLASS.IDENTITY_MARKER,
    spec: '<root>/.steward/project.json',
    dir: '.steward',
    file: 'project.json',
    extension: '.json',
    depth: 2,
    framing: 'json',
    tag: 'NATIVE-mirror',
    id_field: 'project_id',
    // registered_at / registered_path / registration_receipt_id are marker-v2 fields whose
    // VALIDATION is W4's (engine/portfolio/marker.mjs). W2 only discovers and reads them.
    fields: Object.freeze(['project_id', 'registered_at', 'registered_path', 'registration_receipt_id']),
    row_shape: 'not a row - feeds identity binding',
    inventory_version: INVENTORY_VERSION,
    ratified_by: RATIFIED_BY,
  }),
]);

/** The closed-set contract, stated where code can read it. */
export const EXTENSION_GATE = Object.freeze({
  closed: true,
  version: INVENTORY_VERSION,
  next_version: 'inventory-v2',
  ratified_by: RATIFIED_BY,
  refusal_code: 'INVENTORY_EXTENSION_REFUSED',
  how_to_extend:
    'Record a ratification entry naming the new class in an approved inventory-v2, then ' +
    'pass that record to extendInventory(). Editing this table in code without one is a ' +
    'gate violation, not a change.',
});

/**
 * Presence codes for a root. ABSENT and UNREACHABLE are deliberately NOT the same state.
 * Re-exported from STATUS-v1 rather than re-declared: two definitions of ABSENT is exactly
 * the drift W3's lint exists to prevent.
 */
export const PRESENCE = STATUS_PRESENCE;

/**
 * Named hazard codes. A hazard is never an exception and never a silent skip.
 *
 * The first three ARE the STATUS-v1 path-hazard axis and read from it. SKIPPED_CYCLE and
 * WALK_CAP_REACHED are W2-local codes the frozen axis does not carry; they stay named here
 * (and listed in HAZARDS_BEYOND_AXIS below) rather than being folded into a neighbour,
 * because a walk that hit its bound is not an unreadable one.
 */
export const HAZARD = Object.freeze({
  SKIPPED_REPARSE: PATH_HAZARD.SKIPPED_REPARSE,
  PATH_TOO_LONG: PATH_HAZARD.PATH_TOO_LONG,
  CASE_COLLISION: PATH_HAZARD.CASE_COLLISION,
  SKIPPED_CYCLE: 'SKIPPED_CYCLE',
  UNREACHABLE: STATUS_PRESENCE.UNREACHABLE,
  WALK_CAP_REACHED: 'WALK_CAP_REACHED',
});

/**
 * The three codes the plan names as STATUS-v1's path-hazard axis (W3). Kept separate from
 * the two below so the census can report the difference as a GATE ITEM rather than either
 * inventing enum members or laundering a hazard into an axis that does not fit it.
 */
export const PATH_HAZARD_AXIS = Object.freeze([
  HAZARD.SKIPPED_REPARSE,
  HAZARD.PATH_TOO_LONG,
  HAZARD.CASE_COLLISION,
]);

/**
 * Codes W2 needed that the frozen path-hazard axis does not yet carry. Surfaced, never
 * folded into a neighbouring code: SKIPPED_CYCLE is not a reparse point, and a walk that
 * hit its bound is not an unreadable one.
 */
export const HAZARDS_BEYOND_AXIS = Object.freeze([HAZARD.SKIPPED_CYCLE, HAZARD.WALK_CAP_REACHED]);

/** Named parse-failure reasons. UNPARSEABLE without a reason is not a report. */
export const PARSE_REASON = Object.freeze({
  EMPTY_FILE: 'EMPTY_FILE',
  INVALID_UTF8: 'INVALID_UTF8',
  MOJIBAKE: INTEGRITY.MOJIBAKE,
  INVALID_JSON: 'INVALID_JSON',
  INVALID_JSON_LINE: 'INVALID_JSON_LINE',
  NOT_AN_OBJECT: 'NOT_AN_OBJECT',
  MISSING_FIELD: 'MISSING_FIELD',
  UNREADABLE: 'UNREADABLE',
  UNKNOWN_CLASS: 'UNKNOWN_CLASS',
});

/** Windows MAX_PATH. A path at or past it needs the extended-length prefix to open. */
export const MAX_PATH = 260;

/** The extended-length prefix: the four characters backslash backslash question backslash. */
export const EXTENDED_PREFIX = '\\\\?\\';

/**
 * Directories never descended into. Each one is RECORDED as excluded with its path, so
 * "we did not look there" is a statement in the output rather than an omission in it.
 */
export const EXCLUDED_DIR_NAMES = Object.freeze([
  '.git',
  '.hg',
  '.svn',
  'node_modules',
  'vendor',
  'dist',
  'build',
  'coverage',
  '__pycache__',
  '.cache',
]);

/**
 * The walk's bound. An unbounded walk over a real portfolio is a hang waiting to happen,
 * and an unnamed bound cannot be tested; reaching it is reported as WALK_CAP_REACHED
 * rather than quietly returning a short list. W4 owns the ratified number.
 */
export const DEFAULT_WALK_CAP = 50000;

/**
 * Carriers the CURRENT engine writes that inventory-v1 does not name. This table exists
 * only so the census can WRITE UP the mismatch as a gate item; nothing here is ever
 * ingested, and nothing here is a discovery path. Deleting a row would hide a real gap.
 */
export const LEGACY_CARRIERS = Object.freeze([
  Object.freeze({ file: 'strip.json', array: 'receipts', class: CLASS.RECEIPT }),
  Object.freeze({ file: 'strip.json', array: 'instruments', class: CLASS.INSTRUMENT }),
  Object.freeze({ file: 'roadmap.json', array: 'roadmap_events', class: CLASS.ROADMAP_EVENT }),
]);

// -- pure path helpers --------------------------------------------------------

/**
 * Order two directory entries: lowercased name first, raw name as the tie-break.
 *
 * String#toLowerCase and the relational operators are locale-INDEPENDENT by
 * specification. localeCompare and toLocaleLowerCase are not, and a walk ordered by
 * either genuinely produces a different sequence under a different ICU locale - which
 * would make "the rebuild is byte-equal across machines" false for reasons no test on one
 * machine could ever surface.
 *
 * @param {string} a @param {string} b @returns {-1|0|1}
 */
export function compareEntryNames(a, b) {
  const la = String(a).toLowerCase();
  const lb = String(b).toLowerCase();
  if (la < lb) return -1;
  if (la > lb) return 1;
  const ra = String(a);
  const rb = String(b);
  if (ra < rb) return -1;
  if (ra > rb) return 1;
  return 0;
}

/** @param {string[]} names @returns {string[]} a new array in walk order */
export function sortEntryNames(names) {
  return [...names].sort(compareEntryNames);
}

/**
 * Group entry names that differ only by case.
 *
 * @param {string[]} names
 * @returns {Map<string, string[]>} lowercased name -> the colliding names, sorted; groups
 *   of one are omitted
 */
export function detectCaseCollisions(names) {
  const groups = new Map();
  for (const name of names) {
    const key = String(name).toLowerCase();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(String(name));
  }
  const collisions = new Map();
  for (const [key, group] of groups) {
    if (group.length > 1) collisions.set(key, sortEntryNames(group));
  }
  return collisions;
}

/** @param {string} p @returns {boolean} whether p is a UNC / network path */
export function isUncPath(p) {
  let s = String(p);
  if (s.startsWith(EXTENDED_PREFIX)) {
    return s.slice(EXTENDED_PREFIX.length).toUpperCase().startsWith('UNC\\');
  }
  return s.startsWith('\\\\') || s.startsWith('//');
}

/** @param {string} p @returns {boolean} whether p is at or past MAX_PATH */
export function isOverMaxPath(p) {
  return String(p).length >= MAX_PATH;
}

/**
 * The form of a path that can actually be opened. On Windows an absolute path at or past
 * MAX_PATH is rewritten through the extended-length prefix; everything else is returned
 * unchanged so no non-Windows host ever sees a Windows-only string.
 *
 * @param {string} p @returns {string}
 */
export function openablePath(p) {
  const s = String(p);
  if (process.platform !== 'win32') return s;
  if (s.startsWith(EXTENDED_PREFIX)) return s;
  if (!isOverMaxPath(s)) return s;
  if (!path.isAbsolute(s)) return s;
  const norm = path.resolve(s);
  if (norm.startsWith('\\\\')) return `${EXTENDED_PREFIX}UNC\\${norm.slice(2)}`;
  return `${EXTENDED_PREFIX}${norm}`;
}

/** @param {string} rel @returns {string} a root-relative path with POSIX separators */
export function toPosix(rel) {
  return String(rel).split(path.sep).join('/');
}

/**
 * Root-relative POSIX path, the only path form that appears in an ordered walk list.
 * Absolute paths carry the host in them and would make two machines disagree by
 * construction.
 *
 * @param {string} rootAbs @param {string} abs @returns {string}
 */
export function relFromRoot(rootAbs, abs) {
  const rel = path.relative(rootAbs, abs);
  return rel === '' ? '.' : toPosix(rel);
}

/**
 * ABSENT vs UNREACHABLE, as distinct states.
 *
 * ABSENT means exactly one thing: ENOENT on the root while its parent is readable - the
 * steward lost track of a directory that could have been there. Anything else (a denied
 * ACL, a busy handle, an offline placeholder, a network failure) is UNREACHABLE, and a
 * UNC root that fails is UNREACHABLE for ANY error code including ENOENT: a host that is
 * not answering cannot tell us the share is gone.
 *
 * @param {NodeJS.ErrnoException} err @param {string} rootAbs
 * @param {{statSync?: Function}} [opts]
 * @returns {{presence: string, reason: string}}
 */
export function classifyRootFailure(err, rootAbs, opts = {}) {
  // No errno from the OS is literally an unknown cause; the token reads from STATUS-v1 so
  // this file declares no status literal of its own.
  const code = err && err.code ? err.code : UNKNOWN_TOKEN;
  if (isUncPath(rootAbs)) {
    return { presence: PRESENCE.UNREACHABLE, reason: `UNC_ROOT_${code}` };
  }
  if (code !== 'ENOENT') {
    return { presence: PRESENCE.UNREACHABLE, reason: code };
  }
  const statSync = opts.statSync ?? fs.statSync;
  const abs = path.resolve(rootAbs);
  const parent = path.dirname(abs);
  if (parent === abs) {
    return { presence: PRESENCE.UNREACHABLE, reason: 'ENOENT_AT_FILESYSTEM_ROOT' };
  }
  try {
    statSync(openablePath(parent));
    return { presence: PRESENCE.ABSENT, reason: 'ENOENT' };
  } catch {
    return { presence: PRESENCE.UNREACHABLE, reason: 'ENOENT_PARENT_UNREADABLE' };
  }
}

/**
 * The cycle guard's key: the Windows file index (bigint stat's `ino` IS the file index on
 * win32), qualified by device. A non-bigint stat returns ino 0 on Windows, which would
 * collapse every directory onto one key and refuse the entire walk after the first
 * directory - hence the bigint call, and hence the explicit zero check before trusting it.
 *
 * @param {string} abs @param {{statSync?: Function}} [fsx]
 * @returns {string}
 */
export function directoryKey(abs, fsx = fs) {
  const statSync = fsx && typeof fsx.statSync === 'function' ? fsx.statSync : fs.statSync;
  try {
    const st = statSync(openablePath(abs), { bigint: true });
    if (st && st.ino !== undefined && st.ino !== 0n) return `idx:${st.dev}:${st.ino}`;
  } catch {
    /* fall through to the path key: a directory we cannot stat still must not be re-entered */
  }
  return `path:${path.resolve(abs).toLowerCase()}`;
}

// -- classification -----------------------------------------------------------

/** @param {string} className @returns {object|null} the frozen inventory entry */
export function inventoryEntryFor(className) {
  return INVENTORY_V1.find((e) => e.class === className) ?? null;
}

/**
 * Which inventory-v1 class does this root-relative path belong to?
 *
 * Matching is case-insensitive because Windows path comparison is, and a receipt in
 * `Receipts/` is the same receipt. `null` is a real answer - it means UNCLASSIFIED, which
 * is a row, not a discard.
 *
 * @param {string} rel root-relative path (POSIX or native separators)
 * @returns {object|null} the inventory entry, or null for UNCLASSIFIED
 */
export function classifyRelPath(rel) {
  const segs = toPosix(rel).split('/').filter((s) => s !== '' && s !== '.');
  for (const entry of INVENTORY_V1) {
    if (segs.length !== entry.depth) continue;
    if (segs[0].toLowerCase() !== entry.dir.toLowerCase()) continue;
    const name = segs[segs.length - 1];
    if (entry.file) {
      if (name.toLowerCase() === entry.file.toLowerCase()) return entry;
      continue;
    }
    const ext = entry.extension.toLowerCase();
    if (name.length > ext.length && name.toLowerCase().endsWith(ext)) return entry;
  }
  return null;
}

/** @param {string} rel @returns {string} the class name, or UNCLASSIFIED */
export function classNameForRelPath(rel) {
  const entry = classifyRelPath(rel);
  return entry ? entry.class : UNCLASSIFIED;
}

// -- the extension gate -------------------------------------------------------

/**
 * Extend the closed set - which is only possible with a ratification record in hand.
 *
 * Returns a NEW table and never mutates INVENTORY_V1, so even a ratified extension cannot
 * retroactively change what a already-shipped rebuild considered in scope.
 *
 * @param {object} entry the proposed class
 * @param {{version?: string, ratified_by?: string, classes?: string[]}} [ratification]
 * @returns {ReadonlyArray<object>} a new frozen table
 * @throws {Error & {code: string, problems: string[]}} INVENTORY_EXTENSION_REFUSED
 */
export function extendInventory(entry, ratification) {
  const problems = [];

  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    problems.push('entry must be an object describing the proposed class');
  } else {
    for (const field of ['class', 'spec', 'dir', 'framing', 'id_field']) {
      if (typeof entry[field] !== 'string' || entry[field].trim() === '') {
        problems.push(`entry.${field} is required`);
      }
    }
    if (entry.class && INVENTORY_CLASSES.includes(entry.class)) {
      problems.push(`class '${entry.class}' is already in ${INVENTORY_VERSION}`);
    }
  }

  if (!ratification || typeof ratification !== 'object') {
    problems.push('a ratification record is required - a code edit alone is a gate violation');
  } else {
    if (ratification.version !== EXTENSION_GATE.next_version) {
      problems.push(`ratification.version must be '${EXTENSION_GATE.next_version}'`);
    }
    if (typeof ratification.ratified_by !== 'string' || ratification.ratified_by.trim() === '') {
      problems.push('ratification.ratified_by must name the approving gate entry');
    }
    const classes = Array.isArray(ratification.classes) ? ratification.classes : [];
    if (!entry || !classes.includes(entry.class)) {
      problems.push('ratification.classes must name the class being added');
    }
  }

  if (problems.length) {
    const err = new Error(
      `${EXTENSION_GATE.refusal_code}: ${INVENTORY_VERSION} is a closed set - ${problems.join('; ')}`,
    );
    err.code = EXTENSION_GATE.refusal_code;
    err.problems = problems;
    throw err;
  }

  return Object.freeze([
    ...INVENTORY_V1,
    Object.freeze({
      ...entry,
      inventory_version: ratification.version,
      ratified_by: ratification.ratified_by,
    }),
  ]);
}

/**
 * Self-check on the frozen table: every entry carries provenance, every class is unique,
 * every discovery path is unique. A table that lost its provenance is a table nobody
 * ratified.
 *
 * @param {ReadonlyArray<object>} [table]
 * @returns {{ok: boolean, violations: string[]}}
 */
export function inventoryIntegrity(table = INVENTORY_V1) {
  const violations = [];
  const classes = new Set();
  const specs = new Set();
  for (const entry of table) {
    if (!entry.ratified_by) violations.push(`${entry.class}: no ratified_by`);
    if (!entry.inventory_version) violations.push(`${entry.class}: no inventory_version`);
    if (classes.has(entry.class)) violations.push(`${entry.class}: duplicate class`);
    classes.add(entry.class);
    if (specs.has(entry.spec)) violations.push(`${entry.class}: duplicate discovery path`);
    specs.add(entry.spec);
    if (!Object.isFrozen(entry)) violations.push(`${entry.class}: entry is not frozen`);
  }
  return { ok: violations.length === 0, violations };
}

// -- the walk -----------------------------------------------------------------

/**
 * Is this entry a reparse point?
 *
 * The dirent's own answer is trusted first. The lstat second opinion exists because a
 * Windows junction is a reparse point that some listings report as a plain directory, and
 * a junction mistaken for a directory is precisely the cycle this walk must not enter: the
 * cycle guard would then be the only thing standing between the census and a walk that
 * descends into an ancestor. It is one extra call per DIRECTORY entry, never per file,
 * and a failure to stat is answered "not a reparse point" so an unreadable entry falls
 * through to the ordinary UNREACHABLE path instead of being mislabelled here.
 *
 * @param {object} ent @param {string} childAbs @param {object} fsx
 * @returns {boolean}
 */
function isReparsePoint(ent, childAbs, fsx) {
  if (typeof ent.isSymbolicLink === 'function' && ent.isSymbolicLink()) return true;
  if (typeof ent.isDirectory !== 'function' || !ent.isDirectory()) return false;
  const lstatSync = fsx && typeof fsx.lstatSync === 'function' ? fsx.lstatSync : fs.lstatSync;
  try {
    return lstatSync(openablePath(childAbs)).isSymbolicLink();
  } catch {
    return false;
  }
}

/**
 * @typedef {object} WalkFile
 * @property {string} rel root-relative POSIX path
 * @property {string} abs
 * @property {string|null} class inventory-v1 class, or null for UNCLASSIFIED
 * @property {string[]} hazards hazard codes attached to this entry
 */

/**
 * @typedef {object} WalkResult
 * @property {string} root absolute root
 * @property {string} label a host-free label for reports
 * @property {string} presence LIVE | ABSENT | UNREACHABLE
 * @property {string|null} reason why, when not LIVE
 * @property {string[]} order every path visited, in walk order (directories carry '/',
 *   reparse points carry '@') - the artifact the determinism test compares
 * @property {WalkFile[]} files
 * @property {Array<object>} hazards
 * @property {Array<{path: string, reason: string}>} excluded
 * @property {boolean} truncated whether the walk hit its bound
 * @property {number} entries_seen
 */

/**
 * Walk one registered root under the NG-2 contract.
 *
 * @param {string} rootInput
 * @param {{
 *   fs?: object, readdir?: Function, maxEntries?: number, label?: string,
 *   visited?: Set<string>, excludeDirNames?: string[]
 * }} [opts]
 * @returns {WalkResult}
 */
export function walkRoot(rootInput, opts = {}) {
  const fsx = opts.fs ?? fs;
  const statSync = fsx.statSync ?? fs.statSync;
  const readlinkSync = fsx.readlinkSync ?? fs.readlinkSync;
  const cap = Number.isInteger(opts.maxEntries) && opts.maxEntries > 0 ? opts.maxEntries : DEFAULT_WALK_CAP;
  const excluded = new Set((opts.excludeDirNames ?? EXCLUDED_DIR_NAMES).map((n) => n.toLowerCase()));
  const visited = opts.visited instanceof Set ? opts.visited : new Set();
  const rootAbs = path.resolve(rootInput);

  /** @type {WalkResult} */
  const result = {
    root: rootAbs,
    label: opts.label ?? path.basename(rootAbs),
    presence: PRESENCE.LIVE,
    reason: null,
    order: [],
    files: [],
    hazards: [],
    excluded: [],
    truncated: false,
    entries_seen: 0,
  };

  const addHazard = (code, rel, extra = {}) => {
    result.hazards.push({ code, path: rel, skipped: false, ...extra });
  };

  let rootStat;
  try {
    rootStat = statSync(openablePath(rootAbs));
  } catch (err) {
    const verdict = classifyRootFailure(err, rootAbs, { statSync });
    result.presence = verdict.presence;
    result.reason = verdict.reason;
    if (verdict.presence === PRESENCE.UNREACHABLE) {
      addHazard(HAZARD.UNREACHABLE, '.', { skipped: true, detail: verdict.reason });
    }
    return result;
  }
  if (!rootStat.isDirectory()) {
    result.presence = PRESENCE.UNREACHABLE;
    result.reason = 'NOT_A_DIRECTORY';
    addHazard(HAZARD.UNREACHABLE, '.', { skipped: true, detail: 'NOT_A_DIRECTORY' });
    return result;
  }

  if (isOverMaxPath(rootAbs)) {
    addHazard(HAZARD.PATH_TOO_LONG, '.', {
      opened_via: process.platform === 'win32' ? EXTENDED_PREFIX : null,
      resolved: true,
      length: rootAbs.length,
    });
  }

  visited.add(directoryKey(rootAbs, fsx));

  const stack = [{ abs: rootAbs, rel: '.' }];
  let capped = false;

  while (stack.length && !capped) {
    const dir = stack.pop();
    result.order.push(`${dir.rel}/`);

    let entries;
    try {
      entries = opts.readdir
        ? opts.readdir(dir.abs, dir.rel)
        : fsx.readdirSync(openablePath(dir.abs), { withFileTypes: true });
    } catch (err) {
      const code = err && err.code ? err.code : UNKNOWN_TOKEN;
      if (isOverMaxPath(dir.abs)) {
        addHazard(HAZARD.PATH_TOO_LONG, dir.rel, {
          skipped: true,
          resolved: false,
          length: dir.abs.length,
          detail: code,
        });
      } else {
        addHazard(HAZARD.UNREACHABLE, dir.rel, { skipped: true, detail: code });
      }
      continue;
    }

    const list = Array.isArray(entries) ? entries : [];
    const collisions = detectCaseCollisions(list.map((e) => e.name));
    const sorted = [...list].sort((a, b) => compareEntryNames(a.name, b.name));
    const subdirs = [];

    for (const ent of sorted) {
      if (result.entries_seen >= cap) {
        result.truncated = true;
        capped = true;
        addHazard(HAZARD.WALK_CAP_REACHED, dir.rel, {
          skipped: true,
          cap,
          detail: `walk stopped at ${cap} entries; the remainder of this root was not visited`,
        });
        break;
      }
      result.entries_seen += 1;

      const name = ent.name;
      const childRel = dir.rel === '.' ? name : `${dir.rel}/${name}`;
      const childAbs = path.join(dir.abs, name);
      const entryHazards = [];

      const peers = collisions.get(name.toLowerCase());
      if (peers) {
        // BOTH paths are named. Reporting only the second one would make the outcome
        // depend on walk order, which is the exact property this walk is defending.
        entryHazards.push(HAZARD.CASE_COLLISION);
        addHazard(HAZARD.CASE_COLLISION, childRel, {
          peers: peers.map((p) => (dir.rel === '.' ? p : `${dir.rel}/${p}`)),
          detail: 'two entries in one directory differ only by case',
        });
      }

      if (isOverMaxPath(childAbs)) {
        entryHazards.push(HAZARD.PATH_TOO_LONG);
        addHazard(HAZARD.PATH_TOO_LONG, childRel, {
          opened_via: process.platform === 'win32' ? EXTENDED_PREFIX : null,
          resolved: true,
          length: childAbs.length,
          detail: 'opened through the extended-length prefix',
        });
      }

      if (isReparsePoint(ent, childAbs, fsx)) {
        let target = null;
        try {
          target = readlinkSync(openablePath(childAbs));
        } catch {
          target = null;
        }
        addHazard(HAZARD.SKIPPED_REPARSE, childRel, {
          skipped: true,
          target: target === null ? null : toPosix(target),
          detail: 'reparse point recorded and NOT followed',
        });
        result.order.push(`${childRel}@`);
        continue;
      }

      if (typeof ent.isDirectory === 'function' && ent.isDirectory()) {
        if (excluded.has(name.toLowerCase())) {
          result.excluded.push({ path: childRel, reason: 'EXCLUDED_DIR_NAME' });
          continue;
        }
        const key = directoryKey(childAbs, fsx);
        if (visited.has(key)) {
          addHazard(HAZARD.SKIPPED_CYCLE, childRel, {
            skipped: true,
            detail: 'directory already visited in this walk - re-entry refused',
          });
          continue;
        }
        visited.add(key);
        subdirs.push({ abs: childAbs, rel: childRel });
        continue;
      }

      // Files, and anything exotic that is neither a directory nor a reparse point: it is
      // recorded rather than dropped, because a discovery that silently ignores a byte
      // source is exactly the failure this module exists to prevent.
      const entry = classifyRelPath(childRel);
      result.files.push({
        rel: childRel,
        abs: childAbs,
        class: entry ? entry.class : null,
        hazards: entryHazards,
      });
      result.order.push(childRel);
    }

    // Reversed, because the stack pops from the end and the sorted order must survive.
    for (let i = subdirs.length - 1; i >= 0; i -= 1) stack.push(subdirs[i]);
  }

  return result;
}

/**
 * Walk several registered roots. Roots are walked in the order given (the caller's
 * registration order is meaningful); each root gets its OWN cycle-guard set, so two roots
 * that happen to share a directory each report it rather than one of them silently losing
 * it to the other's visited set.
 *
 * @param {string[]} roots
 * @param {object} [opts] as walkRoot, plus {labels?: string[]}
 * @returns {{roots: WalkResult[], walked_at_version: string}}
 */
export function walkPortfolio(roots, opts = {}) {
  const list = Array.isArray(roots) ? roots : [];
  const results = list.map((root, i) =>
    walkRoot(root, {
      ...opts,
      visited: new Set(),
      label: Array.isArray(opts.labels) ? opts.labels[i] : undefined,
    }),
  );
  return { roots: results, walked_at_version: INVENTORY_VERSION };
}

// -- per-class parse entry points ---------------------------------------------

/** @returns {object} a failed parse result */
function parseFailure(className, reason, detail, opts = {}) {
  return {
    ok: false,
    class: className,
    path: opts.path ?? null,
    reason,
    detail: detail ?? null,
    records: [],
    record_count: 0,
  };
}

/** @param {object} obj @param {object} entry @returns {object} the declared field set */
function projectFields(obj, entry) {
  const record = {};
  for (const field of entry.fields) {
    record[field] = obj[field] === undefined ? null : obj[field];
  }
  return record;
}

/** @returns {string|null} a MISSING_FIELD detail, or null when the id is present */
function idProblem(obj, entry) {
  const value = obj[entry.id_field];
  if (typeof value === 'string' && value.trim() !== '') return null;
  if (typeof value === 'number' && Number.isFinite(value)) return null;
  return entry.id_field;
}

/**
 * Parse bytes (or text) as a named inventory-v1 class.
 *
 * The order of the checks is the point. MOJIBAKE is tested BEFORE JSON validity because a
 * mojibake document is perfectly valid JSON - a parser-first pipeline reports it as
 * healthy and folds the damage into a content hash forever (W1). EMPTY is tested before
 * both because "valid but empty" is its own row in the failure tables, never UNKNOWN.
 *
 * @param {string} className
 * @param {Buffer|Uint8Array|string} input
 * @param {{path?: string}} [opts]
 * @returns {{ok: boolean, class: string, path: string|null, records: object[], record_count: number, reason?: string, detail?: string|null, framing?: string}}
 */
export function parseBytes(className, input, opts = {}) {
  const entry = inventoryEntryFor(className);
  if (!entry) {
    return parseFailure(className, PARSE_REASON.UNKNOWN_CLASS, `not an ${INVENTORY_VERSION} class`, opts);
  }

  const bytes = Buffer.isBuffer(input) ? input : Buffer.from(String(input), 'utf8');
  if (bytes.length === 0) return parseFailure(className, PARSE_REASON.EMPTY_FILE, 'zero bytes', opts);
  if (!isValidUtf8(bytes)) {
    return parseFailure(className, PARSE_REASON.INVALID_UTF8, 'bytes do not decode as UTF-8', opts);
  }

  const text = bytes.toString('utf8');
  if (text.trim() === '') {
    return parseFailure(className, PARSE_REASON.EMPTY_FILE, 'whitespace only', opts);
  }

  const scan = scanBytesForMojibake(bytes);
  if (!scan.clean) {
    const first = scan.findings[0];
    return parseFailure(
      className,
      PARSE_REASON.MOJIBAKE,
      `byte ${scan.first_offset}: ${first ? first.signature : 'unknown signature'}`,
      opts,
    );
  }

  return entry.framing === 'jsonl'
    ? parseJsonlText(entry, text, opts)
    : parseJsonText(entry, text, opts);
}

/** @returns {object} parse result for a single-document class */
function parseJsonText(entry, text, opts) {
  let value;
  try {
    value = JSON.parse(text);
  } catch (err) {
    return parseFailure(entry.class, PARSE_REASON.INVALID_JSON, err.message, opts);
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return parseFailure(entry.class, PARSE_REASON.NOT_AN_OBJECT, `got ${Array.isArray(value) ? 'array' : typeof value}`, opts);
  }
  const missing = idProblem(value, entry);
  if (missing) {
    return parseFailure(entry.class, PARSE_REASON.MISSING_FIELD, missing, opts);
  }
  return {
    ok: true,
    class: entry.class,
    path: opts.path ?? null,
    framing: entry.framing,
    records: [projectFields(value, entry)],
    record_count: 1,
  };
}

/**
 * JSONL: one event per line. A single bad line fails the FILE, naming the line number -
 * a file half of whose events are unreadable is not a healthy file, and quietly keeping
 * the good half would put a number in the census that no rebuild could reproduce.
 *
 * @returns {object} parse result
 */
function parseJsonlText(entry, text, opts) {
  const lines = text.split(/\r?\n/);
  const records = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim() === '') continue;
    let value;
    try {
      value = JSON.parse(line);
    } catch (err) {
      return parseFailure(entry.class, PARSE_REASON.INVALID_JSON_LINE, `line ${i + 1}: ${err.message}`, opts);
    }
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      return parseFailure(entry.class, PARSE_REASON.NOT_AN_OBJECT, `line ${i + 1}`, opts);
    }
    const missing = idProblem(value, entry);
    if (missing) {
      return parseFailure(entry.class, PARSE_REASON.MISSING_FIELD, `line ${i + 1}: ${missing}`, opts);
    }
    records.push(projectFields(value, entry));
  }
  if (records.length === 0) {
    return parseFailure(entry.class, PARSE_REASON.EMPTY_FILE, 'no event lines', opts);
  }
  return {
    ok: true,
    class: entry.class,
    path: opts.path ?? null,
    framing: entry.framing,
    records,
    record_count: records.length,
  };
}

/** @param {Buffer|string} input @param {object} [opts] */
export function parseReceipt(input, opts) {
  return parseBytes(CLASS.RECEIPT, input, opts);
}

/** @param {Buffer|string} input @param {object} [opts] */
export function parseInstrument(input, opts) {
  return parseBytes(CLASS.INSTRUMENT, input, opts);
}

/** @param {Buffer|string} input @param {object} [opts] */
export function parseRoadmapEvents(input, opts) {
  return parseBytes(CLASS.ROADMAP_EVENT, input, opts);
}

/** @param {Buffer|string} input @param {object} [opts] */
export function parseIdentityMarker(input, opts) {
  return parseBytes(CLASS.IDENTITY_MARKER, input, opts);
}

/** The per-class parse entry points, keyed by class name. */
export const PARSE_ENTRY_POINTS = Object.freeze({
  [CLASS.RECEIPT]: parseReceipt,
  [CLASS.INSTRUMENT]: parseInstrument,
  [CLASS.ROADMAP_EVENT]: parseRoadmapEvents,
  [CLASS.IDENTITY_MARKER]: parseIdentityMarker,
});

/**
 * Read a discovered file and parse it as its class.
 *
 * @param {string} className @param {string} absPath
 * @returns {object} parse result, always carrying `path`
 */
export function parseInventoryFile(className, absPath) {
  let bytes;
  try {
    // encoding-lint: raw-bytes - INVALID_UTF8 and MOJIBAKE are DISTINCT named states and a
    // decoded read erases both (Node substitutes U+FFFD and never tells anyone), so the
    // bytes are read undecoded here and decoded deliberately inside parseBytes.
    bytes = fs.readFileSync(openablePath(absPath));
  } catch (err) {
    return parseFailure(className, PARSE_REASON.UNREADABLE, err.code ?? String(err), { path: absPath });
  }
  return { ...parseBytes(className, bytes, { path: absPath }), path: absPath };
}

// -- the mismatch probe (report only) -----------------------------------------

/**
 * Look for content the CURRENT engine writes into carriers inventory-v1 does not name.
 *
 * This NEVER ingests and NEVER extends the table. Its entire product is a gate item: "the
 * frozen discovery path found nothing, and here is where the content actually is, with a
 * count". Silence here would let W4 propose caps from a portfolio it measured as empty.
 *
 * @param {string} rootAbs
 * @param {{readFileSync?: Function, existsSync?: Function}} [fsx]
 * @returns {Array<{code: string, class: string, expected_path: string, observed_carrier: string, observed_items: number|null, detail: string}>}
 */
export function probeLegacyCarriers(rootAbs, fsx = fs) {
  const readFileSync = fsx.readFileSync ?? fs.readFileSync;
  const existsSync = fsx.existsSync ?? fs.existsSync;
  const findings = [];
  const cache = new Map();

  for (const carrier of LEGACY_CARRIERS) {
    const abs = path.join(path.resolve(rootAbs), carrier.file);
    if (!cache.has(carrier.file)) {
      let parsed = null;
      try {
        if (existsSync(openablePath(abs))) {
          parsed = JSON.parse(readFileSync(openablePath(abs), 'utf8'));
        }
      } catch {
        parsed = null;
      }
      cache.set(carrier.file, parsed);
    }
    const doc = cache.get(carrier.file);
    if (!doc || typeof doc !== 'object') continue;
    const arr = doc[carrier.array];
    if (!Array.isArray(arr)) continue;
    const entry = inventoryEntryFor(carrier.class);
    findings.push({
      code: 'INVENTORY_PATH_MISMATCH',
      class: carrier.class,
      expected_path: entry ? entry.spec : `<root>/${carrier.class}`,
      observed_carrier: `${carrier.file}#${carrier.array}[]`,
      observed_items: arr.length,
      detail:
        `${INVENTORY_VERSION} discovers ${carrier.class} at ${entry ? entry.spec : '(unknown)'}, ` +
        `but this root carries ${arr.length} item(s) inside ${carrier.file}#${carrier.array}[]. ` +
        'Written up as a gate item; NOT ingested and NOT silently added to the closed set.',
    });
  }

  return findings;
}

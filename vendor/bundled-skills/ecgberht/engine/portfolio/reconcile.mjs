/**
 * W12 - `steward reconcile`: the ONLY route by which a binding ever moves.
 *
 * WHY THIS FILE EXISTS. C4 says a project_id survives a move. The tempting way to deliver
 * that is to make the steward clever: walk around, find the marker, notice it is somewhere
 * new, and rebind. That implementation is one `xcopy` away from a disaster, and the
 * disaster is silent. A marker is a FILE. Any process, any backup tool, any operator with a
 * mouse can produce a byte-perfect second copy of one, and an engine that obeys markers on
 * sight will bind a project's entire recorded history to whichever copy it happened to walk
 * first. Nothing throws. Nothing is logged. The portfolio simply starts answering questions
 * about the wrong directory.
 *
 * So this module is built on one sentence: A MARKER IS A CLAIM, NOT AN INSTRUCTION. Three
 * consequences, and every function below is one of them:
 *
 *   1. NOTHING REBINDS AUTOMATICALLY. There is no code path from "a marker was observed" to
 *      "a binding changed". The only two paths are `--moved` and `--claim`, both of which an
 *      operator types, and both of which name the paths explicitly so the operator's own
 *      belief about where the project is becomes part of the evidence.
 *
 *   2. `--scan` PROPOSES AND NEVER BINDS. It is the bounded, hazard-safe search an operator
 *      runs when they do not know where a project went. It returns candidates and the exact
 *      command that would bind each one. It appends nothing. That is not a nicety of the
 *      current implementation: scanning is how a hijacked marker gets in front of the engine
 *      in the first place, so the search surface is precisely the surface that must be inert.
 *
 *   3. TWO PLACES IS A REFUSAL, ON EVERY ROUTE. If the same project_id is live at two
 *      locations, no route rebinds - not the one that looks obvious, not the one the
 *      operator asked for. The refusal names both paths and offers exactly one escape:
 *      `steward reconcile --claim <project_id> <path>`, which is an explicit, recorded human
 *      decision rather than an inference. The claim event names BOTH paths and the loser's
 *      marker hash, so the record says which bytes lost as well as which won.
 *
 * WHY THE LOSER IS NOT REGISTERED FOR THE OPERATOR (NG-3). A clone that inherits history by
 * accident is the injury this wave exists to prevent, so `--claim` deliberately leaves the
 * losing directory UNBOUND and tells the operator what to do with it. It does not helpfully
 * mint an id for it: minting one would mean the engine decided that a copy is a project,
 * which is a judgement only the person who made the copy can make. The instruction is
 * precise about the one obstacle, too - the loser still carries the winner's marker, and
 * `steward register` refuses a marked root by design (REGISTER_ALREADY_MARKED), so the
 * operator is told to move that marker aside first rather than being handed a command that
 * will refuse.
 *
 * WHAT THIS MODULE NEVER WRITES. It never writes a marker. Not on `--moved`, where the
 * marker at the new path is already the bytes being verified, and not on `--claim`, where
 * rewriting the loser's marker would destroy the only git-free evidence of what happened.
 * The marker's `registered_path` therefore keeps saying where the root was REGISTERED - it
 * is a registration record, not a current-location cache - and where the project is NOW is
 * the registry view's answer, materialized from NATIVE events. One fact, one home.
 *
 * Stdlib only. Every status code and every user-visible sentence is read from the frozen
 * W3 reconcile table; nothing here composes a sentence of its own except the three success
 * rows, which the tables (a catalogue of FAILURE states) do not cover.
 */

import fs from 'node:fs';
import path from 'node:path';

import { INDEX_READ_CODE, INDEX_WRITE_CODE, appendEvents, indexPathsFrom } from '../append-log.mjs';
import { scanFileForMojibake } from '../encoding.mjs';
import { CAPS } from './caps.mjs';
import { SURFACE, fillRowText, rowForCode, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import { pathKey, samePath } from './identity.mjs';
import {
  CLASS,
  DEFAULT_WALK_CAP,
  HAZARD,
  classifyRelPath,
  openablePath,
  toPosix,
  walkRoot,
} from './inventory.mjs';
import { MARKER_DIR, MARKER_FILE, MARKER_REFUSAL, MARKER_STATUS, markerPathFor, readMarker } from './marker.mjs';
import { knownLocationsFor } from './rebuild.mjs';
import {
  RECONCILE_MODE,
  makeReconcileEvent,
  materializeRegistry,
  readRegistry,
  resolveProject,
} from './registry.mjs';
import { classifyRootStatus } from './root-status.mjs';
import { INTEGRITY, PRESENCE, assertStatusCode, axisOf } from './status.mjs';

/** The verb's frozen contract version. */
export const RECONCILE_VERSION = 'reconcile-v1';

/** The verb's name, as an operator types it. */
export const RECONCILE_VERB = 'reconcile';

/** The failure-table surface these rows belong to. */
export const RECONCILE_SURFACE = SURFACE.RECONCILE;

/**
 * The three routes, spelled as the operator spells them. There is no fourth, and there is
 * no default: a `reconcile` with no route names nothing, and an engine that guessed which
 * route was meant would be inferring a rebinding, which is the one thing this verb exists
 * to refuse.
 */
export const RECONCILE_ROUTE = Object.freeze({
  MOVED: '--moved',
  SCAN: '--scan',
  CLAIM: '--claim',
});

/** @type {ReadonlyArray<string>} */
export const RECONCILE_ROUTES = Object.freeze(Object.values(RECONCILE_ROUTE));

/**
 * Which routes can change a binding, as DATA rather than as a promise in a comment. A test
 * reads this and asserts the scan route's log head is unmoved; a future route added without
 * a decision here is a route with no answer to the question.
 */
export const ROUTE_BINDS = Object.freeze({
  [RECONCILE_ROUTE.MOVED]: true,
  [RECONCILE_ROUTE.SCAN]: false,
  [RECONCILE_ROUTE.CLAIM]: true,
});

/** The reconcile mode each binding route records in its NATIVE event. */
export const ROUTE_MODE = Object.freeze({
  [RECONCILE_ROUTE.MOVED]: RECONCILE_MODE.MOVED,
  [RECONCILE_ROUTE.CLAIM]: RECONCILE_MODE.CLAIM,
});

/**
 * The frozen W3 rows this verb reports through. The names are declared here so call sites
 * read a constant rather than typing a string, and every one is checked against the table
 * at module load - a row renamed in W3 fails the import rather than failing an operator.
 */
export const RECONCILE_CODE = Object.freeze({
  TARGET_ABSENT: 'RECONCILE_TARGET_ABSENT',
  TARGET_UNREACHABLE: 'RECONCILE_TARGET_UNREACHABLE',
  MARKER_ABSENT: 'RECONCILE_MARKER_ABSENT',
  SCAN_BOUND_EXCEEDED: 'RECONCILE_SCAN_BOUND_EXCEEDED',
  LOCK_TIMEOUT: 'RECONCILE_LOCK_TIMEOUT',
  MARKER_UNPARSEABLE: 'RECONCILE_MARKER_UNPARSEABLE',
  MARKER_MOJIBAKE: 'RECONCILE_MARKER_MOJIBAKE',
  TWO_PLACES: 'RECONCILE_TWO_PLACES',
  MARKER_TAMPERED: 'RECONCILE_MARKER_TAMPERED',
  REGISTRY_UNREADABLE: 'RECONCILE_REGISTRY_UNREADABLE',
  SCAN_EMPTY: 'RECONCILE_SCAN_EMPTY',
  NOT_DECIDABLE: 'RECONCILE_UNKNOWN',
  SKIPPED_REPARSE: 'RECONCILE_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'RECONCILE_PATH_TOO_LONG',
  CASE_COLLISION: 'RECONCILE_CASE_COLLISION',
});

for (const code of Object.values(RECONCILE_CODE)) {
  if (rowForCode(code) === null) {
    throw new Error(`reconcile: ${code} is not a frozen failure-table row`);
  }
}

/** The success codes. Not table rows: the seven tables catalogue failure states. */
export const RECONCILE_MOVED_OK = 'RECONCILE_MOVED_OK';

/** @see RECONCILE_MOVED_OK */
export const RECONCILE_CLAIM_OK = 'RECONCILE_CLAIM_OK';

/** @see RECONCILE_MOVED_OK */
export const RECONCILE_SCAN_OK = 'RECONCILE_SCAN_OK';

/**
 * The three sentences this module owns. `{placeholders}` are filled at the call site; an
 * unfilled one is left VISIBLE, exactly as the W3 tables leave theirs, because a sentence
 * with a silent gap in it reads as though the missing fact had been reported.
 */
export const RECONCILE_ROWS = Object.freeze({
  [RECONCILE_MOVED_OK]: Object.freeze({
    code: RECONCILE_MOVED_OK,
    status: INTEGRITY.OK,
    text:
      'project {project_id} now resolves to {to_path}. One NATIVE reconcile event at log seq '
      + '{seq} records the move from {from_path} and the full content hash of the marker that '
      + 'proved it ({marker_sha256}). No id was minted, no row was dropped, and no marker was '
      + 'rewritten: the binding moved, the identity did not.',
  }),
  [RECONCILE_CLAIM_OK]: Object.freeze({
    code: RECONCILE_CLAIM_OK,
    status: INTEGRITY.OK,
    text:
      'project {project_id} is bound to {to_path} by explicit claim. One NATIVE reconcile event '
      + 'at log seq {seq} names both paths and records the marker hash of the copy that did NOT '
      + "win ({marker_sha256}). {from_path} is left unbound and inherits none of this project's "
      + 'history. If those bytes are meant to be a project of their own, move {loser_marker} '
      + 'aside by hand and run steward register {from_path} - a clone never inherits a history '
      + "by accident, and register refuses a root still carrying another project's marker.",
  }),
  [RECONCILE_SCAN_OK]: Object.freeze({
    code: RECONCILE_SCAN_OK,
    status: INTEGRITY.OK,
    text:
      'the bounded scan of {roots} search root(s) visited {entries} entr(ies) and PROPOSES '
      + '{proposals} marker candidate(s). Nothing was bound and nothing was appended: a scan is '
      + 'evidence, and only steward reconcile --moved <old> <new> or steward reconcile --claim '
      + '<project_id> <path> changes a binding.',
  }),
});

/** @type {ReadonlyArray<string>} every code this verb can return, for a test to enumerate. */
export const RECONCILE_CODES = Object.freeze([
  ...Object.keys(RECONCILE_ROWS),
  ...Object.values(RECONCILE_CODE),
]);

/**
 * How a candidate found by `--scan` is DISPOSED OF - which is never "bound". Each value is
 * an instruction to a human, and the proposal carries the exact command beside it.
 */
export const PROPOSAL = Object.freeze({
  MOVED: 'PROPOSE_MOVED',
  BOUND_ALREADY: 'PROPOSE_NOTHING_BOUND_HERE',
  CLAIM: 'PROPOSE_CLAIM',
  FOREIGN: 'PROPOSE_FOREIGN_MARKER',
  DAMAGED: 'PROPOSE_REPAIR_MARKER',
});

/** @type {ReadonlyArray<string>} */
export const PROPOSALS = Object.freeze(Object.values(PROPOSAL));

/**
 * marker refusal -> the reconcile row that reports it.
 *
 * Derived from marker.mjs's own MARKER_STATUS table rather than retyped, so a marker
 * refusal cannot acquire a second opinion about which row owns it. ONE deliberate override
 * is declared here rather than hidden: MARKER_UNREADABLE maps in W4 to the registry-
 * unreadable row, whose frozen sentence is about the INDEX HOME. On this surface the thing
 * that could not be read is the marker at the path the operator just named, and reading the
 * operator a sentence about a different file is a small lie told confidently. The
 * target-unreachable row is the true sentence for that state, and it carries the errno.
 */
export const ROW_FOR_MARKER_REFUSAL = Object.freeze({
  ...Object.fromEntries(
    Object.entries(MARKER_STATUS).map(([refusal, mapped]) => [refusal, mapped.failure_row]),
  ),
  [MARKER_REFUSAL.UNREADABLE]: RECONCILE_CODE.TARGET_UNREACHABLE,
});

/** The one override above, stated where a test can assert it is deliberate. */
export const MARKER_ROW_OVERRIDES = Object.freeze([
  Object.freeze({
    refusal: MARKER_REFUSAL.UNREADABLE,
    declared_by_marker_module: MARKER_STATUS[MARKER_REFUSAL.UNREADABLE].failure_row,
    used_here: RECONCILE_CODE.TARGET_UNREACHABLE,
    why:
      'the registry-unreadable sentence is about the index home; what failed here is the '
      + 'marker at the path the operator named, and the target-unreachable row says so with '
      + 'its errno.',
  }),
]);

/** Walk hazard -> the reconcile row that reports it, so a hazard is never laundered. */
export const ROW_FOR_HAZARD = Object.freeze({
  [HAZARD.SKIPPED_REPARSE]: RECONCILE_CODE.SKIPPED_REPARSE,
  [HAZARD.PATH_TOO_LONG]: RECONCILE_CODE.PATH_TOO_LONG,
  [HAZARD.CASE_COLLISION]: RECONCILE_CODE.CASE_COLLISION,
});

// -- outcomes ------------------------------------------------------------------

/**
 * Build an outcome for one of this verb's codes.
 *
 * Frozen failure rows are rendered by the table (one home for the status and the sentence);
 * the three success rows are rendered here in the same SHAPE, so a caller can switch on one
 * vocabulary and never has to ask which kind of row it is holding.
 *
 * @param {string} code
 * @param {Record<string, unknown>} [params] placeholder values
 * @param {object} [extra] carried onto the outcome verbatim; `ok` reaches the table
 * @returns {Readonly<object>}
 */
export function reconcileOutcome(code, params = {}, extra = {}) {
  const { ok, ...rest } = extra;
  const local = RECONCILE_ROWS[code];
  const base = local === undefined
    ? rowOutcome(code, params, { ok })
    : Object.freeze({
      ok: ok !== false,
      code,
      surface: RECONCILE_SURFACE,
      state: null,
      status: assertStatusCode(local.status, `reconcile row ${code}`),
      axis: axisOf(local.status),
      class: null,
      text: fillRowText(local.text, params),
      detail: Object.freeze({ ...params }),
    });
  return Object.freeze({ version: RECONCILE_VERSION, verb: RECONCILE_VERB, ...base, ...rest });
}

/** @param {string} code @returns {string} the row's raw text, placeholders unfilled */
export function reconcileRowText(code) {
  const local = RECONCILE_ROWS[code];
  if (local !== undefined) return local.text;
  const row = rowForCode(code);
  if (row === null) throw new Error(`reconcile: ${code} is not a frozen reconcile row`);
  return row.text;
}

/**
 * The rows this wave owns, READ from the table rather than restated. A list typed by hand
 * here would quietly claim rows another wave is responsible for.
 *
 * @returns {ReadonlyArray<string>}
 */
export function reconcileRowsOwnedByThisWave() {
  return Object.freeze(
    rowsForSurface(RECONCILE_SURFACE).filter((r) => r.wave === 'W12').map((r) => r.code),
  );
}

/** @returns {ReadonlyArray<string>} every frozen reconcile row code, in table order */
export function reconcileRowCodes() {
  return Object.freeze(rowsForSurface(RECONCILE_SURFACE).map((r) => r.code));
}

// -- the commands this verb prints ---------------------------------------------

/** @param {string} oldPath @param {string} newPath @returns {string} */
export function movedCommandFor(oldPath, newPath) {
  return `steward ${RECONCILE_VERB} ${RECONCILE_ROUTE.MOVED} ${path.resolve(String(oldPath))} ${path.resolve(String(newPath))}`;
}

/** @param {string} projectId @param {string} targetPath @returns {string} */
export function claimCommandFor(projectId, targetPath) {
  return `steward ${RECONCILE_VERB} ${RECONCILE_ROUTE.CLAIM} ${projectId} ${path.resolve(String(targetPath))}`;
}

/**
 * What an operator must do with a directory this registry will not bind: the marker has to
 * go first, because register refuses a marked root by design.
 *
 * @param {string} rootPath @returns {string}
 */
export function reRegisterInstructionFor(rootPath) {
  const root = path.resolve(String(rootPath));
  return (
    `move ${markerPathFor(root)} aside by hand, then run steward register ${root}; `
    + 'this binds nothing to the history of the project whose marker it was carrying'
  );
}

// -- reading a claim -----------------------------------------------------------

/** @param {object} opts @returns {object} the fs facade, under either spelling */
function fsFrom(opts) {
  return opts.fsx ?? opts.fs ?? fs;
}

/**
 * Read the marker at a directory and normalize it into a CLAIM.
 *
 * "Claim" rather than "identity" is the whole point of the naming: what comes back is what
 * some bytes on disk assert about themselves, before anything has decided whether to
 * believe them.
 *
 * @param {string} rootPath
 * @param {{fs?: object, fsx?: object}} [opts]
 * @returns {Readonly<{ok: boolean, path: string, marker_path: string, project_id: string|null,
 *            marker: object|null, marker_sha256: string|null, code: string|null,
 *            row: string|null, detail: string|null}>}
 */
export function markerClaimAt(rootPath, opts = {}) {
  const root = path.resolve(String(rootPath));
  const read = readMarker(root, { fs: fsFrom(opts) });
  if (read.ok) {
    return Object.freeze({
      ok: true,
      path: root,
      marker_path: read.path,
      project_id: read.marker.project_id,
      marker: read.marker,
      marker_sha256: read.hash,
      code: null,
      row: null,
      detail: null,
    });
  }
  return Object.freeze({
    ok: false,
    path: root,
    marker_path: read.path,
    project_id: null,
    marker: null,
    marker_sha256: null,
    code: read.code,
    row: ROW_FOR_MARKER_REFUSAL[read.code] ?? RECONCILE_CODE.NOT_DECIDABLE,
    detail: read.problems && read.problems[0] ? read.problems[0].detail : read.code,
  });
}

/**
 * Turn a failed claim into the outcome its row owns.
 *
 * The MOJIBAKE row wants a byte offset, and it gets a real one: the file is re-scanned by
 * the W1 detector rather than having a number parsed back out of a sentence. If that scan
 * cannot run, the placeholder is left visible instead of being filled with a guess.
 *
 * @param {Readonly<object>} claim a failed markerClaimAt result
 * @param {{route?: string}} [extra]
 * @returns {Readonly<object>}
 */
export function claimRefusalOutcome(claim, extra = {}) {
  const row = claim.row;
  const params = { path: claim.path, reason: claim.detail };
  if (row === RECONCILE_CODE.TARGET_UNREACHABLE) {
    params.errno = claim.code;
  }
  if (row === RECONCILE_CODE.MARKER_MOJIBAKE) {
    try {
      const scan = scanFileForMojibake(claim.marker_path);
      if (scan && scan.first_offset !== null && scan.first_offset !== undefined) {
        params.offset = scan.first_offset;
      }
    } catch {
      /* an unscannable file leaves {offset} visible, which is the honest rendering */
    }
  }
  if (row === RECONCILE_CODE.MARKER_ABSENT) {
    params.path = claim.path;
  }
  return reconcileOutcome(row, params, { ...extra, marker_path: claim.marker_path, marker_code: claim.code });
}

/**
 * Does this marker agree with the registration event that minted its id?
 *
 * Every marker-v2 field has a counterpart in the NATIVE registration event, because the
 * event recorded the hash of the exact bytes the marker was written from. So disagreement
 * on ANY field means these are not the bytes the log says exist - the marker was edited, or
 * composed by something else - and a rebinding decided on an edited claim is a rebinding
 * decided by whoever did the editing.
 *
 * @param {object} marker a validated marker-v2
 * @param {object} project a registry view entry
 * @returns {Readonly<{ok: boolean, field: string|null, expected: string|null, observed: string|null}>}
 */
export function markerAgreesWithRegistration(marker, project) {
  const disagree = (field, expected, observed) =>
    Object.freeze({ ok: false, field, expected: String(expected), observed: String(observed) });

  if (marker.project_id !== project.project_id) {
    return disagree('project_id', project.project_id, marker.project_id);
  }
  if (!samePath(marker.registered_path, project.root)) {
    return disagree('registered_path', project.root, marker.registered_path);
  }
  if (marker.registration_receipt_id !== project.registration_receipt_id) {
    return disagree('registration_receipt_id', project.registration_receipt_id, marker.registration_receipt_id);
  }
  if (marker.registered_at !== project.registered_at) {
    return disagree('registered_at', project.registered_at, marker.registered_at);
  }
  return Object.freeze({ ok: true, field: null, expected: null, observed: null });
}

// -- the two-places rule, applied identically on every route --------------------

/**
 * Every live marker carrying this project_id, across a set of directories.
 *
 * The set is CLOSED and supplied by the caller - the registry's known locations, the bounded
 * neighbourhood of the paths the command named, and whatever the operator or a scan supplied.
 * Nothing HERE searches the filesystem: this function reads the markers at the directories it
 * is handed and nothing else, so the rule it applies cannot depend on how the set was widened.
 *
 * @param {string} projectId
 * @param {ReadonlyArray<string>} locations
 * @param {{fs?: object, fsx?: object}} [opts]
 * @returns {Readonly<{claims: ReadonlyArray<object>, damaged: ReadonlyArray<object>,
 *            locations: ReadonlyArray<string>}>}
 */
export function observeIdentityClaims(projectId, locations, opts = {}) {
  const id = String(projectId);
  const claims = [];
  const damaged = [];
  const seen = new Set();
  const visited = [];

  for (const location of locations ?? []) {
    const key = pathKey(location);
    if (seen.has(key)) continue;
    seen.add(key);
    visited.push(path.resolve(String(location)));

    const claim = markerClaimAt(location, opts);
    if (claim.ok) {
      if (claim.project_id === id) claims.push(claim);
      continue;
    }
    // A marker that could not be READ is not evidence of a second copy - it is evidence of
    // nothing, and folding it into a conflict would let an unplugged share look like a clone.
    if (claim.code !== MARKER_REFUSAL.ABSENT && claim.code !== MARKER_REFUSAL.UNREADABLE) {
      damaged.push(claim);
    }
  }

  const sorted = claims.slice().sort((a, b) => (pathKey(a.path) < pathKey(b.path) ? -1 : 1));
  return Object.freeze({
    claims: Object.freeze(sorted),
    damaged: Object.freeze(damaged),
    locations: Object.freeze(visited),
  });
}

/**
 * The two-places refusal, or null when the claim is unambiguous.
 *
 * Applied to `--moved` EXACTLY as to `--scan` and `--claim`, from this one function, so the
 * three routes cannot drift into three different ideas of what "ambiguous" means. The rule:
 * if any directory OTHER than the one being bound holds a live marker for this id, refuse -
 * whether that other directory is the old path the operator just typed, a location the log
 * has named before, or a candidate a scan turned up.
 *
 * @param {string} projectId
 * @param {string} targetPath the path that WOULD be bound
 * @param {ReadonlyArray<string>} locations
 * @param {{fs?: object, fsx?: object, route?: string}} [opts]
 * @returns {Readonly<object>|null}
 */
export function twoPlacesRefusal(projectId, targetPath, locations, opts = {}) {
  const target = path.resolve(String(targetPath));
  const observed = observeIdentityClaims(projectId, locations, opts);
  const others = observed.claims.filter((c) => !samePath(c.path, target));
  if (others.length === 0) return null;

  const named = observed.claims.map((c) => c.path);
  return reconcileOutcome(
    RECONCILE_CODE.TWO_PLACES,
    { project_id: projectId, path: target, other_path: others[0].path },
    {
      route: opts.route ?? null,
      project_id: projectId,
      paths: Object.freeze(named),
      claims: observed.claims,
      escape: claimCommandFor(projectId, target),
      bound: false,
      bindings_changed: 0,
    },
  );
}

/**
 * How many directory entries the neighbourhood probe below will look at. The walk's own
 * cap rather than a second number, because two bounds on one idea is how the two drift.
 */
export const NEIGHBOURHOOD_ENTRIES_CAP = DEFAULT_WALK_CAP;

/**
 * The bounded NEIGHBOURHOOD of the paths a command named: their sibling directories.
 *
 * WHY THE CLOSED SET IS NOT ENOUGH ON ITS OWN. `knownLocationsFor` enumerates every path the
 * LOG has ever named, and for the state the log has seen it is sufficient. It does not cover
 * the state that actually happens: somebody copies a directory beside its original, the
 * original is then moved, and the copy now sits at a path no event ever mentioned. Nothing in
 * the closed set names it, so a rebinding decided on the closed set alone goes through while a
 * second live marker for the same identity is one directory away - and from then on every
 * question the portfolio is asked is answered about whichever copy happened to win. That is
 * precisely the silent failure this verb exists to refuse, so refusing it only when the log
 * had already been told about the copy would be refusing it in the easy case only.
 *
 * WHY THIS IS NOT `--scan` WEARING A DISGUISE. It looks exactly ONE level around the paths the
 * OPERATOR typed - the immediate children of their parent directories - which is one directory
 * listing per parent, no recursion, and no portfolio-wide search. And it is asymmetric by
 * construction: what it finds can only ever ADD a refusal, never a binding. No code path turns
 * a marker seen here into a rebinding; the routes still bind only what the operator named.
 *
 * A neighbourhood that cannot be listed contributes nothing rather than raising, because it is
 * evidence ON TOP OF the closed-set rule and not a replacement for it - the guarantee
 * underneath is unchanged when the probe comes back empty-handed.
 *
 * @param {ReadonlyArray<string>} named the paths the command itself named
 * @param {{fs?: object, fsx?: object, maxEntries?: number}} [opts]
 * @returns {Readonly<{directories: ReadonlyArray<string>, parents: ReadonlyArray<string>,
 *            complete: boolean}>}
 */
export function neighbourhoodOf(named, opts = {}) {
  const fsx = fsFrom(opts);
  const readdirSync = fsx.readdirSync ?? fs.readdirSync;
  const cap = Number.isInteger(opts.maxEntries) && opts.maxEntries > 0
    ? opts.maxEntries
    : NEIGHBOURHOOD_ENTRIES_CAP;

  const parents = new Map();
  for (const candidate of named ?? []) {
    if (typeof candidate !== 'string' || candidate.trim() === '') continue;
    const parent = path.dirname(path.resolve(candidate));
    const key = pathKey(parent);
    if (!parents.has(key)) parents.set(key, parent);
  }

  const found = new Map();
  let seen = 0;
  let complete = true;

  for (const parent of parents.values()) {
    let entries;
    try {
      entries = readdirSync(openablePath(parent), { withFileTypes: true });
    } catch {
      // Unreadable is not empty, and it is not a refusal either: the closed-set rule below
      // is what this probe is adding to, and it is still in force.
      complete = false;
      continue;
    }
    for (const entry of Array.isArray(entries) ? entries : []) {
      if (seen >= cap) {
        complete = false;
        break;
      }
      seen += 1;
      if (typeof entry.isDirectory !== 'function' || !entry.isDirectory()) continue;
      // A reparse point is an ALIAS, and an alias is not a second copy. Following one would
      // let a junction beside a project report the project as being in two places.
      if (typeof entry.isSymbolicLink === 'function' && entry.isSymbolicLink()) continue;
      const abs = path.join(parent, entry.name);
      const key = pathKey(abs);
      if (!found.has(key)) found.set(key, abs);
    }
  }

  return Object.freeze({
    directories: Object.freeze([...found.values()].sort((a, b) => (pathKey(a) < pathKey(b) ? -1 : 1))),
    parents: Object.freeze([...parents.values()]),
    complete,
  });
}

// -- the registry --------------------------------------------------------------

/**
 * Materialize the registry view, or return the refusal that says why not.
 *
 * An index home that does not exist yet is NOT a refusal - it is an empty portfolio, and
 * every route below then reports "this registry never minted that id", which is true and
 * actionable. An index home that exists and cannot be read is a refusal, because rebinding
 * against a registry nobody could read is rebinding on no evidence at all.
 *
 * @param {object} opts @param {string} [route]
 * @returns {Readonly<{ok: boolean, view: object|null, outcome: object|null}>}
 */
function registryOrRefusal(opts, route) {
  const paths = indexPathsFrom(opts);
  const read = readRegistry({ ...opts, home: paths.home });
  if (read.ok) return Object.freeze({ ok: true, view: read.view, outcome: null });

  const absent = read.outcome && read.outcome.status === PRESENCE.ABSENT;
  if (absent) return Object.freeze({ ok: true, view: materializeRegistry([]), outcome: null });

  // A lock this reader could not take is NOT an unreadable registry - the index is fine and
  // somebody else is holding it. It has its own row, and reporting the wrong one would send
  // the operator to repair a store that has nothing wrong with it.
  if (read.outcome && read.outcome.code === INDEX_READ_CODE.LOCK_TIMEOUT) {
    return Object.freeze({
      ok: false,
      view: null,
      outcome: reconcileOutcome(RECONCILE_CODE.LOCK_TIMEOUT, {}, {
        route: route ?? null,
        index_outcome: read.outcome,
        bound: false,
        bindings_changed: 0,
      }),
    });
  }

  const detail = read.outcome ? read.outcome.detail ?? {} : {};
  return Object.freeze({
    ok: false,
    view: null,
    outcome: reconcileOutcome(
      RECONCILE_CODE.REGISTRY_UNREADABLE,
      { errno: detail.errno ?? (read.outcome ? read.outcome.code : RECONCILE_CODE.NOT_DECIDABLE) },
      { route: route ?? null, index_outcome: read.outcome, bound: false, bindings_changed: 0 },
    ),
  });
}

/**
 * Classify the directory a route is pointed at, or return the refusal that says why not.
 *
 * ABSENT and UNREACHABLE stay distinct here for the reason they are distinct everywhere:
 * "you typed a path that is not there" and "your share is not answering" are two different
 * afternoons for the operator.
 *
 * @param {string} targetAbs @param {object} opts @param {string} route
 * @returns {Readonly<object>|null} a refusal, or null when the directory is usable
 */
function targetRefusal(targetAbs, opts, route) {
  const status = classifyRootStatus(targetAbs, { fsx: fsFrom(opts) });
  if (status.presence === PRESENCE.LIVE) return null;
  const code = status.presence === PRESENCE.ABSENT
    ? RECONCILE_CODE.TARGET_ABSENT
    : RECONCILE_CODE.TARGET_UNREACHABLE;
  return reconcileOutcome(
    code,
    { path: targetAbs, errno: status.errno ?? status.reason },
    { route, root_status: status, bound: false, bindings_changed: 0 },
  );
}

/**
 * Append the NATIVE reconcile event, mapping an append failure onto a reconcile row.
 *
 * @param {object} event @param {object} opts @param {string} route
 * @returns {Readonly<{ok: boolean, seq: number|null, outcome: object|null, appended: object|null}>}
 */
function appendReconcileEvent(event, opts, route) {
  const paths = indexPathsFrom(opts);
  const appended = appendEvents([event], { ...opts, home: paths.home, now: opts.now });
  if (appended.ok === true) {
    return Object.freeze({ ok: true, seq: appended.seq, outcome: null, appended });
  }
  if (appended.code === INDEX_WRITE_CODE.LOCK_TIMEOUT) {
    return Object.freeze({
      ok: false,
      seq: null,
      appended,
      outcome: reconcileOutcome(RECONCILE_CODE.LOCK_TIMEOUT, {}, {
        route,
        index_outcome: appended,
        bound: false,
        bindings_changed: 0,
      }),
    });
  }
  return Object.freeze({
    ok: false,
    seq: null,
    appended,
    outcome: reconcileOutcome(
      RECONCILE_CODE.NOT_DECIDABLE,
      { reason: appended.text ? appended.text : appended.code },
      { route, index_outcome: appended, bound: false, bindings_changed: 0 },
    ),
  });
}

// -- route 1: --moved ----------------------------------------------------------

/**
 * `steward reconcile --moved <old> <new>`.
 *
 * The order of the checks IS the contract, and each one exists because skipping it produces
 * a confident wrong answer:
 *
 *   1. the registry, because a claim can only be verified against something;
 *   2. the new directory's presence, because rebinding onto a path the steward could not
 *      even look at is rebinding on evidence it never saw;
 *   3. the marker there, refused rather than defaulted when damaged;
 *   4. the marker against the registration event, field by field - an edited claim is a
 *      claim made by whoever did the editing;
 *   5. two places, from the shared rule above - before anything else about the command is
 *      judged, because a second live copy is the dominant fact about this identity in
 *      whichever direction the rebinding was asked for. The set the rule is applied over is
 *      the log's known locations WIDENED by the bounded neighbourhood of the two paths the
 *      operator typed, because the copy that makes a move unsafe is usually the one sitting
 *      beside it, at a path no event ever named;
 *   6. the operator's own belief: <old> must be where the registry currently binds this
 *      project. If it is not, the operator and the log disagree about the world, and the
 *      binding is left alone rather than moved on a guess about which one is right;
 *   7. and only then the append - after which the verb returns success, because the event
 *      is fsynced before appendEvents reports it durable.
 *
 * @param {string} oldPath @param {string} newPath
 * @param {{home?: string, paths?: object, env?: object, fs?: object, fsx?: object,
 *          now?: number, known_paths?: ReadonlyArray<string>, boundMs?: number,
 *          staleMs?: number, lockOpts?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function reconcileMoved(oldPath, newPath, opts = {}) {
  const route = RECONCILE_ROUTE.MOVED;
  const from = path.resolve(String(oldPath));
  const to = path.resolve(String(newPath));

  const registry = registryOrRefusal(opts, route);
  if (!registry.ok) return registry.outcome;
  const view = registry.view;

  const target = targetRefusal(to, opts, route);
  if (target !== null) return target;

  const claim = markerClaimAt(to, opts);
  if (!claim.ok) return claimRefusalOutcome(claim, { route, bound: false, bindings_changed: 0 });

  const project = resolveProject(view, claim.project_id);
  if (project === null) {
    return reconcileOutcome(
      RECONCILE_CODE.MARKER_TAMPERED,
      { path: to, project_id: claim.project_id },
      {
        route,
        project_id: claim.project_id,
        reason: `no registration event in this log ever minted ${claim.project_id}`,
        bound: false,
        bindings_changed: 0,
      },
    );
  }

  const agreement = markerAgreesWithRegistration(claim.marker, project);
  if (!agreement.ok) {
    return reconcileOutcome(
      RECONCILE_CODE.MARKER_TAMPERED,
      { path: to, project_id: claim.project_id },
      {
        route,
        project_id: claim.project_id,
        disagreement: agreement,
        reason:
          `the marker field ${agreement.field} reads ${agreement.observed}, but the registration `
          + `event for ${claim.project_id} recorded ${agreement.expected}`,
        bound: false,
        bindings_changed: 0,
      },
    );
  }

  // Two places FIRST, and before the question of whether <old> is where the log thought the
  // project was. When a second live copy exists, that is the dominant fact about this
  // identity whichever direction the operator asked to rebind in; answering "your old path
  // is wrong" would send them off to retype the command that this state must refuse.
  const neighbourhood = neighbourhoodOf([from, to], opts);
  const locations = knownLocationsFor(project, [
    from,
    to,
    ...neighbourhood.directories,
    ...(opts.known_paths ?? []),
  ]);
  const conflict = twoPlacesRefusal(claim.project_id, to, locations, { ...opts, route });
  if (conflict !== null) return conflict;

  if (!samePath(project.current_path, from)) {
    return reconcileOutcome(
      RECONCILE_CODE.NOT_DECIDABLE,
      {
        reason:
          `the command names ${from} as the old location of ${claim.project_id}, but this log `
          + `binds that project to ${project.current_path}. The operator and the log disagree `
          + 'about where the project was, so the binding is left where it is rather than moved '
          + `on a guess; if ${project.current_path} is the location that moved, name it`,
      },
      {
        route,
        project_id: claim.project_id,
        bound_path: project.current_path,
        expected_command: movedCommandFor(project.current_path, to),
        bound: false,
        bindings_changed: 0,
      },
    );
  }

  const event = makeReconcileEvent({
    project_id: claim.project_id,
    from_path: from,
    to_path: to,
    mode: ROUTE_MODE[route],
    marker_sha256: claim.marker_sha256,
  });
  const appended = appendReconcileEvent(event, opts, route);
  if (!appended.ok) return appended.outcome;

  return reconcileOutcome(
    RECONCILE_MOVED_OK,
    {
      project_id: claim.project_id,
      from_path: from,
      to_path: to,
      seq: appended.seq,
      marker_sha256: claim.marker_sha256,
    },
    {
      route,
      project_id: claim.project_id,
      from_path: from,
      to_path: to,
      mode: ROUTE_MODE[route],
      event,
      seq: appended.seq,
      marker_sha256: claim.marker_sha256,
      marker_path: claim.marker_path,
      locations,
      // Stated rather than implied: a probe that could not see the whole neighbourhood
      // examined less ground than it set out to, and a reader deserves to know which.
      neighbourhood_complete: neighbourhood.complete,
      bound: true,
      bindings_changed: 1,
      minted: false,
    },
  );
}

// -- route 2: --claim ----------------------------------------------------------

/**
 * `steward reconcile --claim <project_id> <path>` - the ONE escape from NG-3.
 *
 * This is the only route that binds a path while another copy of the same marker is still
 * live, and it is deliberately the most explicit thing an operator can type: they name the
 * id AND the directory, so nothing about the outcome was inferred from the filesystem.
 *
 * The event records BOTH paths and the LOSER's marker hash. Recording the loser rather than
 * the winner is the point: the winner's bytes can be read at the bound path forever, while
 * the losing copy is exactly the thing that will be moved, deleted or forgotten, and its
 * hash is what later lets somebody prove which copy this decision was made against.
 *
 * @param {string} projectId @param {string} targetPath
 * @param {object} [opts] @see reconcileMoved
 * @returns {Readonly<object>}
 */
export function reconcileClaim(projectId, targetPath, opts = {}) {
  const route = RECONCILE_ROUTE.CLAIM;
  const id = String(projectId);
  const to = path.resolve(String(targetPath));

  const registry = registryOrRefusal(opts, route);
  if (!registry.ok) return registry.outcome;
  const view = registry.view;

  const target = targetRefusal(to, opts, route);
  if (target !== null) return target;

  const claim = markerClaimAt(to, opts);
  if (!claim.ok) return claimRefusalOutcome(claim, { route, bound: false, bindings_changed: 0 });

  if (claim.project_id !== id) {
    return reconcileOutcome(
      RECONCILE_CODE.NOT_DECIDABLE,
      {
        reason:
          `${to} carries a marker for project ${claim.project_id}, not the ${id} this claim `
          + "names. Binding it would attach one project's history to another project's bytes, "
          + 'so nothing was changed',
      },
      { route, project_id: id, observed_project_id: claim.project_id, bound: false, bindings_changed: 0 },
    );
  }

  // The registry is consulted AFTER the marker, so the refusal below can name the true
  // state: these bytes claim an identity, and no registration event in this log ever minted
  // it. Asking the registry first would have reported the same row about an argument rather
  // than about a file, and the frozen sentence for that row is about a file.
  const project = resolveProject(view, id);
  if (project === null) {
    return reconcileOutcome(
      RECONCILE_CODE.MARKER_TAMPERED,
      { path: to, project_id: id },
      {
        route,
        project_id: id,
        reason: `no registration event in this log ever minted ${id}`,
        bound: false,
        bindings_changed: 0,
      },
    );
  }

  const agreement = markerAgreesWithRegistration(claim.marker, project);
  if (!agreement.ok) {
    return reconcileOutcome(
      RECONCILE_CODE.MARKER_TAMPERED,
      { path: to, project_id: id },
      {
        route,
        project_id: id,
        disagreement: agreement,
        reason:
          `the marker field ${agreement.field} reads ${agreement.observed}, but the registration `
          + `event for ${id} recorded ${agreement.expected}`,
        bound: false,
        bindings_changed: 0,
      },
    );
  }

  // The losers: every OTHER live copy of this identity among the locations this registry
  // knows about, the neighbourhood of the claimed path, and anything the operator or a scan
  // supplied. The SAME widening as `--moved`, deliberately: a rival copy that made `--moved`
  // refuse must be the rival this claim records as the loser, or the escape from the refusal
  // would write a weaker record of the decision than the refusal itself was made on.
  const neighbourhood = neighbourhoodOf([to, project.current_path], opts);
  const locations = knownLocationsFor(project, [
    to,
    ...neighbourhood.directories,
    ...(opts.known_paths ?? []),
  ]);
  const observed = observeIdentityClaims(id, locations, opts);
  const losers = observed.claims.filter((c) => !samePath(c.path, to));

  // With no loser there is nothing to lose, so the event records the hash of the marker
  // that WAS believed - the claimed one. The field never carries a hash of nothing.
  const loser = losers.length > 0 ? losers[0] : null;
  const fromPath = loser === null ? project.current_path : loser.path;
  const markerSha = loser === null ? claim.marker_sha256 : loser.marker_sha256;

  const event = makeReconcileEvent({
    project_id: id,
    from_path: fromPath,
    to_path: to,
    mode: ROUTE_MODE[route],
    marker_sha256: markerSha,
  });
  const appended = appendReconcileEvent(event, opts, route);
  if (!appended.ok) return appended.outcome;

  const unbound = losers.map((c) => Object.freeze({
    path: c.path,
    marker_path: c.marker_path,
    marker_sha256: c.marker_sha256,
    project_id: id,
    bound: false,
    instruction: reRegisterInstructionFor(c.path),
  }));

  return reconcileOutcome(
    RECONCILE_CLAIM_OK,
    {
      project_id: id,
      from_path: fromPath,
      to_path: to,
      seq: appended.seq,
      marker_sha256: markerSha,
      loser_marker: loser === null ? markerPathFor(fromPath) : loser.marker_path,
    },
    {
      route,
      project_id: id,
      from_path: fromPath,
      to_path: to,
      mode: ROUTE_MODE[route],
      event,
      seq: appended.seq,
      marker_sha256: markerSha,
      paths: Object.freeze([fromPath, to]),
      losers: Object.freeze(unbound),
      locations,
      neighbourhood_complete: neighbourhood.complete,
      bound: true,
      bindings_changed: 1,
      minted: false,
    },
  );
}

// -- route 3: --scan -----------------------------------------------------------

/**
 * Is this walked file a marker, and if so which directory does it claim?
 *
 * The shape is checked through inventory-v1's own classifier rather than by matching
 * strings here: `<root>/.steward/project.json` is an inventory-v1 row, and a second copy of
 * that knowledge in this file would be a second place to edit when it changes. The walk's
 * relative path is deeper than a project root (a search root holds projects, not receipts),
 * so it is the last two segments that are classified.
 *
 * @param {{rel: string, abs: string}} file @returns {string|null} the candidate root
 */
export function markerCandidateRootFor(file) {
  const segs = toPosix(file.rel).split('/').filter((s) => s !== '' && s !== '.');
  if (segs.length < 2) return null;
  const entry = classifyRelPath(segs.slice(-2).join('/'));
  if (entry === null || entry.class !== CLASS.IDENTITY_MARKER) return null;
  return path.dirname(path.dirname(path.resolve(file.abs)));
}

/**
 * `steward reconcile --scan <searchRoot>...` - bounded, hazard-safe, and INERT.
 *
 * It walks user-supplied roots through the W2 walk, so a junction cycle cannot hang it and
 * every NG-2 hazard comes back as a named row rather than an exception or a silent skip. It
 * reads markers, compares them against the registry, and returns PROPOSALS: for each
 * candidate, what it is and the exact command that would act on it.
 *
 * It appends nothing. There is no code path from this function to appendEvents, which is
 * why `bound` is a constant false rather than a variable - the scan surface is exactly the
 * surface a forged marker arrives on, so it is the surface that must not be able to decide
 * anything.
 *
 * @param {string|ReadonlyArray<string>} searchRoots
 * @param {{home?: string, paths?: object, env?: object, fs?: object, fsx?: object,
 *          maxEntries?: number, readdir?: Function}} [opts]
 * @returns {Readonly<object>}
 */
export function reconcileScan(searchRoots, opts = {}) {
  const route = RECONCILE_ROUTE.SCAN;
  const roots = (Array.isArray(searchRoots) ? searchRoots : [searchRoots])
    .filter((r) => typeof r === 'string' && r.trim() !== '')
    .map((r) => path.resolve(String(r)));
  const fsx = fsFrom(opts);
  const cap = Number.isInteger(opts.maxEntries) && opts.maxEntries > 0
    ? opts.maxEntries
    : CAPS.walk_entries;

  const registry = registryOrRefusal(opts, route);
  if (!registry.ok) return registry.outcome;
  const view = registry.view;

  const notices = [];
  const walked = [];
  const candidates = [];
  let entriesSeen = 0;
  let complete = true;

  for (const root of roots) {
    const walk = walkRoot(root, {
      fs: fsx,
      readdir: opts.readdir,
      maxEntries: cap,
      label: path.basename(root),
    });
    entriesSeen += walk.entries_seen;

    if (walk.presence !== PRESENCE.LIVE) {
      complete = false;
      const code = walk.presence === PRESENCE.ABSENT
        ? RECONCILE_CODE.TARGET_ABSENT
        : RECONCILE_CODE.TARGET_UNREACHABLE;
      notices.push(reconcileOutcome(code, { path: root, errno: walk.reason }, { route, root }));
      walked.push(Object.freeze({ root, presence: walk.presence, reason: walk.reason, candidates: 0 }));
      continue;
    }

    // Hazards first, so a candidate list is never read as "and nothing else was there".
    let boundReported = false;
    for (const hazard of walk.hazards) {
      const code = ROW_FOR_HAZARD[hazard.code];
      if (code !== undefined) {
        notices.push(reconcileOutcome(
          code,
          {
            path: path.join(root, ...String(hazard.path).split('/')),
            target: hazard.target ?? null,
            other_path: hazard.peers ? hazard.peers.join(', ') : null,
          },
          { route, root, hazard: Object.freeze({ ...hazard }) },
        ));
        continue;
      }
      if (hazard.code === HAZARD.WALK_CAP_REACHED) {
        boundReported = true;
        notices.push(reconcileOutcome(
          RECONCILE_CODE.SCAN_BOUND_EXCEEDED,
          { path: root, cap },
          { route, root, hazard: Object.freeze({ ...hazard }) },
        ));
      }
    }
    // Reported per root, never once for the batch: a scan of five roots that ran out of
    // budget on the third must say WHICH root it stopped inside, or the operator cannot
    // tell which part of the answer is exhaustive.
    if (walk.truncated && !boundReported) {
      boundReported = true;
      notices.push(reconcileOutcome(RECONCILE_CODE.SCAN_BOUND_EXCEEDED, { path: root, cap }, { route, root }));
    }
    if (boundReported) complete = false;

    let found = 0;
    for (const file of walk.files) {
      const candidateRoot = markerCandidateRootFor(file);
      if (candidateRoot === null) continue;
      found += 1;
      candidates.push(Object.freeze({ root, path: candidateRoot, claim: markerClaimAt(candidateRoot, opts) }));
    }
    walked.push(Object.freeze({ root, presence: walk.presence, reason: null, candidates: found }));
  }

  // One pass over the candidates, so "the same id in two places" means two places SEEN AT
  // ONCE. Across two separate scans it would be an ordinary move, and conflating the two
  // would report a conflict every time a project is relocated.
  const byId = new Map();
  for (const candidate of candidates) {
    if (!candidate.claim.ok) continue;
    const id = candidate.claim.project_id;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(candidate);
  }

  const proposals = [];
  const conflicted = new Set();

  for (const [id, group] of [...byId.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1))) {
    const project = resolveProject(view, id);
    const locations = project === null
      ? group.map((c) => c.path)
      : knownLocationsFor(project, group.map((c) => c.path));
    const observed = observeIdentityClaims(id, locations, opts);
    if (observed.claims.length > 1) {
      conflicted.add(id);
      const named = observed.claims.map((c) => c.path);
      notices.push(reconcileOutcome(
        RECONCILE_CODE.TWO_PLACES,
        { project_id: id, path: named[0], other_path: named[1] },
        { route, project_id: id, paths: Object.freeze(named), bound: false },
      ));
    }
  }

  for (const candidate of candidates) {
    const claim = candidate.claim;
    if (!claim.ok) {
      notices.push(claimRefusalOutcome(claim, { route, search_root: candidate.root }));
      proposals.push(Object.freeze({
        path: claim.path,
        marker_path: claim.marker_path,
        project_id: null,
        marker_sha256: null,
        registered_path: null,
        known: false,
        bound_path: null,
        disposition: PROPOSAL.DAMAGED,
        status: rowForCode(claim.row) ? rowForCode(claim.row).status : INTEGRITY.UNPARSEABLE,
        code: claim.row,
        command: null,
        bound: false,
        text:
          `the marker at ${claim.marker_path} could not be read as a claim (${claim.detail}); it `
          + 'is reported rather than defaulted, and nothing here can be bound until it is repaired '
          + 'or moved aside by hand',
      }));
      continue;
    }

    const id = claim.project_id;
    const project = resolveProject(view, id);
    let disposition;
    let command = null;
    let text;

    if (conflicted.has(id)) {
      disposition = PROPOSAL.CLAIM;
      command = claimCommandFor(id, claim.path);
      text =
        `project ${id} is live at more than one path in this scan, so no implicit route will `
        + `bind any of them. If ${claim.path} is the copy that should carry the history, run the `
        + 'command beside this proposal; the other copy is left unbound and is re-registered as a '
        + 'NEW project only if you decide it is one';
    } else if (project === null) {
      disposition = PROPOSAL.FOREIGN;
      text =
        `the marker at ${claim.marker_path} claims project ${id}, which no registration event in `
        + 'this index ever minted. It may belong to a different index home, or it may be a copy '
        + `of a marker that belongs to another project: ${reRegisterInstructionFor(claim.path)}`;
    } else if (samePath(project.current_path, claim.path)) {
      disposition = PROPOSAL.BOUND_ALREADY;
      text = `project ${id} is already bound to ${claim.path}; this scan proposes no change`;
    } else {
      disposition = PROPOSAL.MOVED;
      command = movedCommandFor(project.current_path, claim.path);
      text =
        `project ${id} is bound to ${project.current_path} and its marker was found at `
        + `${claim.path}. This is a PROPOSAL, not a rebinding: run the command beside it to move `
        + 'the binding, because a marker is a claim and claims are not obeyed on sight';
    }

    proposals.push(Object.freeze({
      path: claim.path,
      marker_path: claim.marker_path,
      project_id: id,
      marker_sha256: claim.marker_sha256,
      registered_path: claim.marker.registered_path,
      known: project !== null,
      bound_path: project === null ? null : project.current_path,
      disposition,
      status: conflicted.has(id) ? INTEGRITY.IDENTITY_CONFLICT : INTEGRITY.OK,
      code: conflicted.has(id) ? RECONCILE_CODE.TWO_PLACES : null,
      command,
      bound: false,
      text,
    }));
  }

  proposals.sort((a, b) => (pathKey(a.path) < pathKey(b.path) ? -1 : 1));

  const codes = Object.freeze([...new Set(notices.map((n) => n.code))]);
  const boundExceeded = codes.includes(RECONCILE_CODE.SCAN_BOUND_EXCEEDED);
  // EMPTY means EMPTY: the search ran, the whole of it, and there was genuinely nothing.
  // A scan that reported ANY hazard looked at a different amount of ground than it set out
  // to, so it reports what it proposes (zero) rather than claiming the ground was bare.
  const empty = proposals.length === 0 && complete && notices.length === 0;

  let code = RECONCILE_SCAN_OK;
  if (boundExceeded) code = RECONCILE_CODE.SCAN_BOUND_EXCEEDED;
  else if (empty) code = RECONCILE_CODE.SCAN_EMPTY;

  const params = code === RECONCILE_SCAN_OK
    ? { roots: roots.length, entries: entriesSeen, proposals: proposals.length }
    : { path: roots.join(', '), cap };

  return reconcileOutcome(code, params, {
    ok: true,
    route,
    roots: Object.freeze(roots),
    walked: Object.freeze(walked),
    proposals: Object.freeze(proposals),
    notices: Object.freeze(notices),
    codes,
    entries_seen: entriesSeen,
    cap,
    complete,
    // Not a variable. There is no path from this function to an append.
    bound: ROUTE_BINDS[RECONCILE_ROUTE.SCAN],
    bindings_changed: 0,
  });
}

// -- the verb ------------------------------------------------------------------

/**
 * `steward reconcile <route> <args...>`.
 *
 * The dispatcher exists to make the absence of an implicit route CHECKABLE. An invocation
 * that names no route, or names one with the wrong number of arguments, is refused with the
 * row that says the binding could not be decided - it is never resolved into "the obvious"
 * route, because the whole verb is built on the position that obvious is not evidence.
 *
 * @param {ReadonlyArray<string>} argv @param {object} [opts]
 * @returns {Readonly<object>}
 */
export function reconcile(argv = [], opts = {}) {
  const args = (Array.isArray(argv) ? argv : [argv]).map((a) => String(a));
  const route = args.find((a) => RECONCILE_ROUTES.includes(a)) ?? null;
  const rest = args.filter((a) => a !== route);

  if (route === null) {
    return reconcileOutcome(
      RECONCILE_CODE.NOT_DECIDABLE,
      {
        reason:
          `no explicit route was named. A binding only ever moves by ${RECONCILE_ROUTE.MOVED} or `
          + `${RECONCILE_ROUTE.CLAIM}, and ${RECONCILE_ROUTE.SCAN} only proposes; there is no `
          + 'implicit fourth route, because inferring which one was meant would be inferring a '
          + 'rebinding',
      },
      { route: null, routes: RECONCILE_ROUTES, bound: false, bindings_changed: 0 },
    );
  }

  if (route === RECONCILE_ROUTE.SCAN) {
    if (rest.length === 0) {
      return reconcileOutcome(
        RECONCILE_CODE.NOT_DECIDABLE,
        { reason: `${RECONCILE_ROUTE.SCAN} needs at least one search root; it never picks one for you` },
        { route, bound: false, bindings_changed: 0 },
      );
    }
    return reconcileScan(rest, opts);
  }

  if (rest.length !== 2) {
    return reconcileOutcome(
      RECONCILE_CODE.NOT_DECIDABLE,
      {
        reason:
          `${route} takes exactly two arguments (`
          + (route === RECONCILE_ROUTE.MOVED ? '<old> <new>' : '<project_id> <path>')
          + `) and was given ${rest.length}`,
      },
      { route, bound: false, bindings_changed: 0 },
    );
  }

  return route === RECONCILE_ROUTE.MOVED
    ? reconcileMoved(rest[0], rest[1], opts)
    : reconcileClaim(rest[0], rest[1], opts);
}

/** The marker path shape this verb searches for, re-exported so a test names it once. */
export const RECONCILE_MARKER_REL = `${MARKER_DIR}/${MARKER_FILE}`;

/**
 * W4 - NG-3 identity, as code rather than as a paragraph.
 *
 * WHY THIS FILE EXISTS. Round 1 found that a cloned root - the most ordinary thing an
 * operator does, `xcopy` a project to try something - forks identity. Two directories then
 * carry the same marker, and every naive implementation does one of three silently wrong
 * things: it binds the last one it walked (so the answer depends on directory order), it
 * counts the project twice (so the portfolio grows by a project that does not exist), or
 * it mints a fresh id for the copy (so the copy inherits the original's history under a
 * new name). All three are quiet. This module makes that case LOUD BY CONSTRUCTION: one
 * project_id seen at two live paths is IDENTITY_CONFLICT, both paths are named, NEITHER is
 * bound, and the project is counted exactly once.
 *
 * THE THREE RULES, in the order they matter:
 *
 *  1. MINTED ONCE, NEVER DERIVED. A project_id comes from crypto.randomUUID at register
 *     time and from nowhere else. It is emphatically not a function of the path - a
 *     derived id changes when a project moves, which destroys the one property C4 exists
 *     to provide, and it collides when two roots share a name. assertIdNotDerivedFromPath
 *     actually CHECKS this rather than asserting it in prose: it recomputes the obvious
 *     derivations (hash of the path, of the resolved path, of the basename, in either
 *     case) and refuses an id that matches any of them.
 *
 *  2. MOVED IS A CANDIDATE, NOT A DECISION. A marker whose registered_path differs from
 *     the directory it was found in is a MOVED candidate and nothing more. It is not
 *     rebound here, because a marker is a claim any byte-copy can forge; the resolution is
 *     the explicit W12 verb. Auto-rebinding on a claim is exactly how a hijack succeeds.
 *
 *  3. A CONFLICT BINDS NOTHING. Not the first path, not the newest, not the one with more
 *     files. Choosing a winner from ambiguous evidence produces an answer that is
 *     confident and wrong; the operator resolves it with `steward reconcile --claim`, and
 *     until they do, both paths are reported and the count does not move.
 *
 * PRESENCE MATTERS. Only LIVE observations can bind or conflict. A registered path that is
 * ABSENT or UNREACHABLE is not evidence of a second copy - it is evidence of nothing, and
 * folding it into a conflict would make an unplugged network share look like a clone.
 *
 * Stdlib only.
 */

import crypto from 'node:crypto';
import path from 'node:path';

import { MARKER_FIELDS, PROJECT_ID_PATTERN } from './marker.mjs';
import { INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The frozen rule set's version. */
export const IDENTITY_VERSION = 'identity-v1';

/**
 * The four bindings an observed project_id can have. CONFLICT is the STATUS-v1 integrity
 * code itself rather than a synonym for it, so a surface cannot render one and mean the
 * other.
 */
export const BINDING = Object.freeze({
  BOUND: 'BOUND',
  MOVED_CANDIDATE: 'MOVED_CANDIDATE',
  CONFLICT: INTEGRITY.IDENTITY_CONFLICT,
  NOT_LIVE: 'NOT_LIVE',
});

/** @type {ReadonlyArray<string>} */
export const BINDINGS = Object.freeze(Object.values(BINDING));

/** The refusals this module raises. */
export const IDENTITY_REFUSAL = Object.freeze({
  ID_DERIVED_FROM_PATH: 'IDENTITY_ID_DERIVED_FROM_PATH',
  ID_MALFORMED: 'IDENTITY_ID_MALFORMED',
  ID_ALREADY_MINTED: 'IDENTITY_ID_ALREADY_MINTED',
  OBSERVATION_MALFORMED: 'IDENTITY_OBSERVATION_MALFORMED',
});

/** The frozen W3 rows this module's verdicts render through. */
export const IDENTITY_FAILURE_ROWS = Object.freeze({
  [BINDING.CONFLICT]: 'REBUILD_IDENTITY_CONFLICT',
  TWO_PLACES: 'RECONCILE_TWO_PLACES',
});

/** A caller-branchable error. */
export class IdentityRefusal extends Error {
  /** @param {string} code @param {string} detail */
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = 'IdentityRefusal';
    this.code = code;
    this.detail = detail;
  }
}

// -- minting -------------------------------------------------------------------

/**
 * Mint a project_id. The ONLY id source in the system.
 *
 * @param {{randomUUID?: () => string}} [opts]
 * @returns {string}
 */
export function mintProjectId(opts = {}) {
  const gen = typeof opts.randomUUID === 'function' ? opts.randomUUID : crypto.randomUUID;
  const id = String(gen());
  if (!PROJECT_ID_PATTERN.test(id)) {
    throw new IdentityRefusal(IDENTITY_REFUSAL.ID_MALFORMED, `${JSON.stringify(id)} is not a lowercase RFC-4122 identifier`);
  }
  return id;
}

/**
 * Mint for a root that has never been registered - and refuse if it has.
 *
 * "Exactly once" is a property of the CALL SITE, not of the generator, so the guard lives
 * where the decision is made: an existing id means the answer already exists and minting a
 * second one would fork the project's history.
 *
 * @param {string} rootAbs
 * @param {{existing_id?: string|null, randomUUID?: () => string}} [opts]
 * @returns {string}
 */
export function mintProjectIdForRoot(rootAbs, opts = {}) {
  const existing = opts.existing_id ?? null;
  if (existing !== null && existing !== undefined && String(existing).trim() !== '') {
    throw new IdentityRefusal(
      IDENTITY_REFUSAL.ID_ALREADY_MINTED,
      `${path.resolve(String(rootAbs))} already carries project_id ${existing}; a second id ` +
        'would fork its history, so registration refuses instead of minting one',
    );
  }
  const id = mintProjectId(opts);
  assertIdNotDerivedFromPath(id, rootAbs);
  return id;
}

/**
 * The obvious ways somebody would derive an id from a path, computed so they can be
 * refused rather than merely discouraged.
 *
 * @param {string} p @returns {string[]} 32-hex-character digests
 */
export function derivedIdCandidates(p) {
  const raw = String(p);
  const resolved = path.resolve(raw);
  const base = path.basename(resolved);
  const inputs = [raw, raw.toLowerCase(), resolved, resolved.toLowerCase(), base, base.toLowerCase()];
  const seen = new Set();
  const digest = (algo, input) => {
    try {
      return crypto.createHash(algo).update(input, 'utf8').digest('hex').slice(0, 32);
    } catch {
      return null;        // a hardened build may refuse an algorithm; that is not a failure here
    }
  };
  for (const input of inputs) {
    for (const algo of ['sha256', 'sha1', 'md5']) {
      const hex = digest(algo, input);
      if (hex !== null) seen.add(hex);
    }
  }
  return Object.freeze([...seen]);
}

/**
 * Refuse an id that is a function of the path.
 *
 * @param {string} id @param {string} observedPath
 * @returns {string} the id, so this can wrap an argument inline
 */
export function assertIdNotDerivedFromPath(id, observedPath) {
  const value = String(id);
  if (!PROJECT_ID_PATTERN.test(value)) {
    throw new IdentityRefusal(
      IDENTITY_REFUSAL.ID_MALFORMED,
      `${JSON.stringify(value)} is not a lowercase RFC-4122 identifier`,
    );
  }
  const hex = value.replace(/-/g, '');
  if (derivedIdCandidates(observedPath).includes(hex)) {
    throw new IdentityRefusal(
      IDENTITY_REFUSAL.ID_DERIVED_FROM_PATH,
      `${value} is a digest of ${path.resolve(String(observedPath))}. An id derived from a path ` +
        'changes when the project moves, which is the one thing stable identity must survive',
    );
  }
  return value;
}

// -- path comparison -----------------------------------------------------------

/**
 * The comparison key for a directory path.
 *
 * Case-insensitive and separator-normalized because this engine is Windows-first, where
 * `<path> and `<path> are one directory. A trailing separator is stripped so a
 * marker recorded with one is not mistaken for a different location.
 *
 * @param {string} p @returns {string}
 */
export function pathKey(p) {
  const resolved = path.resolve(String(p)).replace(/[\\/]+$/, '');
  return resolved.split(/[\\/]/).join('/').toLowerCase();
}

/** @param {string} a @param {string} b @returns {boolean} */
export function samePath(a, b) {
  return pathKey(a) === pathKey(b);
}

/** Deterministic ordering for reported paths: lowercased key, then the raw string. */
function comparePaths(a, b) {
  const ka = pathKey(a);
  const kb = pathKey(b);
  if (ka !== kb) return ka < kb ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

// -- observations --------------------------------------------------------------

/**
 * One sighting of a marker during ONE pass. `path` is the directory the marker was found
 * in; `registered_path` is what the marker itself claims. The two being different is the
 * whole of the MOVED signal.
 *
 * @param {unknown} value @returns {{project_id: string, path: string, registered_path: string|null, presence: string}}
 */
function normalizeObservation(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new IdentityRefusal(IDENTITY_REFUSAL.OBSERVATION_MALFORMED, 'an observation is an object');
  }
  const obs = /** @type {Record<string, unknown>} */ (value);
  const id = typeof obs.project_id === 'string' ? obs.project_id : '';
  if (!PROJECT_ID_PATTERN.test(id)) {
    throw new IdentityRefusal(
      IDENTITY_REFUSAL.OBSERVATION_MALFORMED,
      `observation carries project_id ${JSON.stringify(obs.project_id)}, which is not a minted identifier`,
    );
  }
  if (typeof obs.path !== 'string' || obs.path.trim() === '') {
    throw new IdentityRefusal(IDENTITY_REFUSAL.OBSERVATION_MALFORMED, `observation for ${id} carries no path`);
  }
  const presence = obs.presence ?? PRESENCE.LIVE;
  assertStatusCode(presence, `identity observation for ${id}`);
  if (!Object.values(PRESENCE).includes(/** @type {string} */ (presence))) {
    throw new IdentityRefusal(
      IDENTITY_REFUSAL.OBSERVATION_MALFORMED,
      `observation for ${id} carries ${presence}, which is not a presence code`,
    );
  }
  return {
    project_id: id,
    path: path.resolve(obs.path),
    registered_path:
      typeof obs.registered_path === 'string' && obs.registered_path.trim() !== ''
        ? path.resolve(obs.registered_path)
        : null,
    presence: /** @type {string} */ (presence),
  };
}

/**
 * Classify every project_id observed in ONE pass.
 *
 * The unit is the pass, deliberately. "The same id at two paths" is only a conflict if
 * both were seen in the same sweep; the same id at two paths across two different runs is
 * an ordinary move, and conflating the two would report a conflict every time a project
 * is relocated.
 *
 * @param {Array<object>} observations
 * @returns {{version: string, projects: Array<object>, project_count: number,
 *            conflicts: Array<object>, moved: Array<object>, bound: Array<object>}}
 */
export function classifyObservations(observations = []) {
  if (!Array.isArray(observations)) {
    throw new IdentityRefusal(IDENTITY_REFUSAL.OBSERVATION_MALFORMED, 'observations must be an array');
  }

  /** @type {Map<string, {live: Map<string, object>, other: Map<string, object>}>} */
  const byId = new Map();
  for (const raw of observations) {
    const obs = normalizeObservation(raw);
    if (!byId.has(obs.project_id)) byId.set(obs.project_id, { live: new Map(), other: new Map() });
    const entry = byId.get(obs.project_id);
    // Keyed by path, so walking one directory twice in a pass is ONE sighting. A conflict
    // must mean two places, never one place counted twice.
    const bucket = obs.presence === PRESENCE.LIVE ? entry.live : entry.other;
    if (!bucket.has(pathKey(obs.path))) bucket.set(pathKey(obs.path), obs);
  }

  const projects = [];
  for (const id of [...byId.keys()].sort()) {
    const entry = byId.get(id);
    const live = [...entry.live.values()].sort((a, b) => comparePaths(a.path, b.path));
    const other = [...entry.other.values()].sort((a, b) => comparePaths(a.path, b.path));

    let binding;
    let bound = null;
    let text;

    if (live.length >= 2) {
      binding = BINDING.CONFLICT;
      const named = live.map((o) => o.path);
      text =
        `${INTEGRITY.IDENTITY_CONFLICT}: project ${id} is live at ${named.join(' and ')}. ` +
        'Both paths are reported, neither is bound, the project is counted once, and no new ' +
        `id was minted. Resolve it with: steward reconcile --claim ${id} <path>`;
    } else if (live.length === 1) {
      const only = live[0];
      if (only.registered_path !== null && !samePath(only.registered_path, only.path)) {
        binding = BINDING.MOVED_CANDIDATE;
        text =
          `project ${id} was found at ${only.path} but its marker records ${only.registered_path}. ` +
          'This is a MOVED candidate, not a rebinding: run steward reconcile --moved to bind it, ' +
          'because a marker is a claim and claims are not obeyed on sight';
      } else {
        binding = BINDING.BOUND;
        bound = only.path;
        text = `project ${id} is bound to ${only.path}`;
      }
    } else {
      binding = BINDING.NOT_LIVE;
      const where = other.length > 0 ? other.map((o) => `${o.path} (${o.presence})`).join(', ') : 'nowhere in this pass';
      text =
        `project ${id} was not observed live: ${where}. Its rows are retained and its identity ` +
        'binding is unchanged - absence never rebinds an id';
    }

    projects.push(Object.freeze({
      project_id: id,
      binding,
      bound_path: bound,
      paths: Object.freeze(live.map((o) => o.path)),
      non_live: Object.freeze(other.map((o) => Object.freeze({ path: o.path, presence: o.presence }))),
      registered_paths: Object.freeze(live.map((o) => o.registered_path)),
      counted: 1,
      status: binding === BINDING.CONFLICT ? INTEGRITY.IDENTITY_CONFLICT : null,
      failure_row: binding === BINDING.CONFLICT ? IDENTITY_FAILURE_ROWS[BINDING.CONFLICT] : null,
      text,
    }));
  }

  return Object.freeze({
    version: IDENTITY_VERSION,
    projects: Object.freeze(projects),
    project_count: projects.length,
    conflicts: Object.freeze(projects.filter((p) => p.binding === BINDING.CONFLICT)),
    moved: Object.freeze(projects.filter((p) => p.binding === BINDING.MOVED_CANDIDATE)),
    bound: Object.freeze(projects.filter((p) => p.binding === BINDING.BOUND)),
  });
}

/**
 * Every project_id counted exactly once, whatever its binding. This is the function the
 * portfolio count comes from, so a clone can never inflate the total.
 *
 * @param {{projects: Array<{counted: number}>}} classification @returns {number}
 */
export function countProjects(classification) {
  return classification.projects.reduce((sum, p) => sum + p.counted, 0);
}

/**
 * Classify the markers found during a pass, straight from readMarker() results.
 *
 * @param {Array<{ok: boolean, root?: string, marker?: object|null, presence?: string}>} markerReads
 * @returns {ReturnType<typeof classifyObservations>}
 */
export function classifyMarkerReads(markerReads = []) {
  const observations = [];
  for (const read of markerReads) {
    if (!read || !read.ok || !read.marker) continue;      // damaged markers are a marker.mjs verdict
    observations.push({
      project_id: read.marker.project_id,
      path: read.root ?? path.dirname(path.dirname(String(read.path))),
      registered_path: read.marker.registered_path,
      presence: read.presence ?? PRESENCE.LIVE,
    });
  }
  return classifyObservations(observations);
}

/** The marker fields identity reads. Re-exported so a field rename cannot half-land. */
export const IDENTITY_MARKER_FIELDS = MARKER_FIELDS;

/**
 * Wave 2 — FIXTURE-ONLY enforcement.
 *
 * The vertical slice must never resolve or write a durable project
 * roadmap_events path. Any attempt to resolve a durable path from slice
 * code throws by name. Slice modules import this guard; they never import
 * loadProjectRoadmap / writeProjectRoadmap / appendRoadmapEventDurable.
 *
 * Stdlib only.
 */

import path from 'node:path';

export const FIXTURE_ONLY = true;

/** Named refusal when durable resolution is attempted. */
export const DURABLE_PATH_REFUSED = 'fixture-durable-path-refused';

/**
 * Always throws. Slice code must not resolve durable project paths.
 * Call sites that "look like" durable resolution funnel here so the
 * failure is loud and named — never a silent fallback to cwd.
 *
 * @param {string} [hint] optional context for the error message
 * @returns {never}
 */
export function resolveDurablePath(hint) {
  const detail = hint ? ` (${hint})` : '';
  const err = new Error(
    `FIXTURE-ONLY: durable path resolution is forbidden from the Wave-2 slice${detail}. ` +
      `Inject a temp-directory fixture ledger; never resolve project-root roadmap_events.`,
  );
  err.code = DURABLE_PATH_REFUSED;
  err.name = 'FixtureDurablePathRefused';
  throw err;
}

/**
 * Resolve only an injected fixture root. Absolute or relative paths that
 * look like durable project roots (contain roadmap.json as target) are
 * refused. The caller must pass an already-created temp directory handle.
 *
 * @param {string|null|undefined} fixtureRoot injected temp dir
 * @returns {string}
 */
export function requireFixtureRoot(fixtureRoot) {
  if (fixtureRoot == null || String(fixtureRoot).trim() === '') {
    const err = new Error(
      'FIXTURE-ONLY: fixture ledger root must be injected; durable resolution refused.',
    );
    err.code = DURABLE_PATH_REFUSED;
    err.name = 'FixtureDurablePathRefused';
    throw err;
  }
  const resolved = path.resolve(String(fixtureRoot).trim());
  return resolved;
}

/**
 * True when a module path is under the fixture-slice package (for audits).
 * @param {string} modulePath
 */
export function isFixtureSliceModule(modulePath) {
  const n = String(modulePath).replace(/\\/g, '/');
  return n.includes('/engine/fixture-slice/') || n.endsWith('/engine/fixture-slice');
}

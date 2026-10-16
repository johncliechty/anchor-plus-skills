/**
 * Wave 21 — executor adapter interface.
 *
 * The suite runs against any adapter exposing:
 *   { name, prepareRun, spawn, kill, collect }
 *
 * Stdlib only.
 */

/** Required method names on every adapter. */
export const ADAPTER_METHODS = Object.freeze([
  'prepareRun',
  'spawn',
  'kill',
  'collect',
]);

/**
 * Validate an adapter object. Does not run it.
 *
 * @param {*} adapter
 * @returns {{ ok: true, name: string } | { ok: false, error: string, message: string }}
 */
export function validateAdapter(adapter) {
  if (!adapter || typeof adapter !== 'object') {
    return {
      ok: false,
      error: 'adapter_required',
      message: 'Adapter must be a non-null object with prepareRun/spawn/kill/collect.',
    };
  }
  const name = adapter.name != null ? String(adapter.name) : '';
  if (!name) {
    return {
      ok: false,
      error: 'adapter_name_required',
      message: 'Adapter must declare a non-empty name (e.g. "insession" | "anchor").',
    };
  }
  for (const m of ADAPTER_METHODS) {
    if (typeof adapter[m] !== 'function') {
      return {
        ok: false,
        error: 'adapter_method_missing',
        message: `Adapter "${name}" missing required method ${m}().`,
      };
    }
  }
  return { ok: true, name };
}

/**
 * Known executor slots written into conformance-verdict.json.
 * @type {readonly string[]}
 */
export const EXECUTOR_SLOTS = Object.freeze(['insession', 'anchor']);

/**
 * @param {string} name
 * @returns {boolean}
 */
export function isExecutorSlot(name) {
  return EXECUTOR_SLOTS.includes(String(name));
}

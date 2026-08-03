// engine/agent-seam.mjs — Wave 1: the LLM seam, injected through ctx.
//
// Wave-0 coupling inventory, three records (analyze/debate/compress,
// kind=hardcoded-path): each stage defaulted its agent to a dynamic import of
// `fil<path> — an absolute, machine-local
// path outside the package. On any machine without that exact directory every
// real run failed at the driver import.
//
// The fix from the inventory's proposed-fix field, implemented here: the driver
// is resolved from CONFIGURATION or an ENV VAR, and when it cannot be resolved
// the failure is LOUD at the call site. No absolute path is baked into any
// stage, and a missing driver can never degrade into a clean-looking empty
// report (the failure mode this whole tool exists to not have).

import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** Env vars consulted, in order, for the driver module location. */
export const DRIVER_ENV_VARS = Object.freeze(['TIDY_IDY_DRIVER', 'TRIO_DRIVER', 'TRIO_DRIVER_PATH']);

/** Thrown when no agent seam can be resolved. Never swallowed. */
export class AgentSeamUnavailable extends Error {
  constructor(detail) {
    super(
      'No LLM agent seam is available for this run. ' +
      'Inject one as ctx.agent, or point ' + DRIVER_ENV_VARS.join(' / ') + ' at a driver module exporting makeGeminiCliSeam(). ' +
      'Refusing to continue: an unavailable analysis engine must fail LOUDLY, never report a clean project. ' +
      (detail ? `(${detail})` : ''));
    this.name = 'AgentSeamUnavailable';
  }
}

/**
 * Convert a driver path/URL into a string `import()` will accept.
 * Critical on Windows: `<path> must become `fil<path> not be
 * treated as a `c:` URL scheme.
 */
export function driverImportSpec(driverPath) {
  const raw = String(driverPath || '').trim();
  if (!raw) throw new AgentSeamUnavailable('empty driver path');
  // Already a supported module URL.
  if (/^(file|data|node):/i.test(raw)) return raw;
  // Windows drive path (C:\... or C:/...) — NOT a URL scheme.
  if (/^[a-zA-Z]:[\\/]/.test(raw)) {
    return pathToFileURL(path.resolve(raw)).href;
  }
  // UNC path
  if (raw.startsWith('\\\\') || raw.startsWith('//')) {
    return pathToFileURL(path.resolve(raw)).href;
  }
  // Other scheme-looking strings (https:, etc.) — pass through.
  if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) return raw;
  return pathToFileURL(path.resolve(raw)).href;
}

/**
 * Resolve the agent function for a run.
 *
 * Resolution order (first hit wins):
 *   1. an explicitly injected `agent` (tests, callers, the Wave-5 launcher)
 *   2. `driverPath` from .tidy-idy config / call options
 *   3. one of the DRIVER_ENV_VARS
 * Anything else → AgentSeamUnavailable at the moment the seam is needed.
 *
 * @param {{agent?: Function, driverPath?: string, model?: string, log?: Function, env?: object}} opts
 * @returns {Function} async (prompt, {schema, label}) => parsed result
 */
export function resolveAgent({ agent = null, driverPath = null, model = null, log = () => {}, env = process.env } = {}) {
  if (typeof agent === 'function') return agent;

  const fromEnv = DRIVER_ENV_VARS.map((k) => env[k]).find((v) => v && String(v).trim());
  const resolvedDriver = driverPath || fromEnv || null;

  if (!resolvedDriver) {
    // Return a thunk that throws WHEN USED, so a run whose mode never needs an
    // LLM (advisory / heuristic-only) is not blocked by an absent driver, while
    // a run that does need one fails loudly at the call site rather than
    // silently producing nothing.
    return async () => { throw new AgentSeamUnavailable('no ctx.agent and no driver env var set'); };
  }

  return async (prompt, callOpts = {}) => {
    let mod;
    // Windows drive paths look like URL schemes (`C:\...` matches /^[a-z]+:/i).
    // Only treat real module URLs as already-specced; always file-URL absolute paths.
    const spec = driverImportSpec(resolvedDriver);
    try {
      mod = await import(spec);
    } catch (err) {
      throw new AgentSeamUnavailable(`driver '${resolvedDriver}' could not be imported: ${err.message}`);
    }
    if (typeof mod.makeGeminiCliSeam !== 'function') {
      throw new AgentSeamUnavailable(`driver '${resolvedDriver}' does not export makeGeminiCliSeam()`);
    }
    const chosenModel = model || env.GEMINI_MODEL || env.TRIO_MODEL || mod.DEFAULT_GEMINI_CLI_MODEL;
    const seam = mod.makeGeminiCliSeam({ model: chosenModel, role: 'review', log });
    return seam.agent(prompt, callOpts);
  };
}

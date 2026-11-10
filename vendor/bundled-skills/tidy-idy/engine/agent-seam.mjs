// engine/agent-seam.mjs — Wave 1: the LLM seam, injected through ctx.
//
// Wave-0 coupling inventory, three records (analyze/debate/compress,
// kind=hardcoded-path): each stage defaulted its agent to a dynamic import of
// `fil<path> — an absolute, machine-local
// path outside the package. On any machine without that exact directory every
// real run failed at the driver import.
//
// The shared default is Trio's receipt-bearing runAgent. A legacy driver module
// remains loadable for old fixtures/config, but production family choice comes
// from Anchor settings / model_prefs through Trio, never from TRIO_DRIVER text
// misread as a module path.

import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** Legacy module-location overrides. TRIO_DRIVER is a driver name, not a path. */
export const DRIVER_ENV_VARS = Object.freeze(['TIDY_IDY_DRIVER', 'TRIO_DRIVER_PATH']);

/** Thrown when no agent seam can be resolved. Never swallowed. */
export class AgentSeamUnavailable extends Error {
  constructor(detail) {
    super(
      'No LLM agent seam is available for this run. ' +
      'Inject ctx.agent/runAgent, install the shared Trio sibling, or point ' + DRIVER_ENV_VARS.join(' / ') + ' at a compatible module. ' +
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

/** Shared Trio location relative to the checked-out Foundry + Trio workspace. */
export function resolveTrioIndexSpec({ driverPath = null, env = process.env } = {}) {
  const fromEnv = DRIVER_ENV_VARS.map((key) => env[key])
    .find((value) => value && String(value).trim());
  const override = driverPath || fromEnv || null;
  return override
    ? driverImportSpec(override)
    : new URL('../../../../trio/drivers/index.mjs', import.meta.url).href;
}

/** Tidy's call labels map to the universal Trio role taxonomy. */
export function roleForTidyCall(callOpts = {}) {
  if (typeof callOpts.role === 'string' && callOpts.role.trim()) {
    return callOpts.role.trim().toLowerCase();
  }
  const label = String(callOpts.label || '').trim().toLowerCase();
  if (label.startsWith('compress')) return 'synthesizer';
  if (label.startsWith('judge')) return 'judge';
  if (label.startsWith('attacker')) return 'attacker';
  return 'reviewer';
}

/**
 * Resolve the agent function for a run.
 *
 * Resolution order (first hit wins):
 *   1. an explicitly injected `agent` (tests, callers, the Wave-5 launcher)
 *   2. injected/shared Trio `runAgent`
 *   3. a legacy compatible module selected by driverPath / DRIVER_ENV_VARS
 *   4. the shared Trio sibling next to Skill Foundry
 *
 * @param {{agent?: Function, runAgent?: Function, driverPath?: string, model?: string,
 *   log?: Function, env?: object, target?: string, importModule?: Function,
 *   onReceipt?: Function}} opts
 * @returns {Function} async (prompt, {schema, label}) => parsed result
 */
export function resolveAgent({
  agent = null,
  runAgent = null,
  driverPath = null,
  model = null,
  log = () => {},
  env = process.env,
  target = process.cwd(),
  importModule = (spec) => import(spec),
  onReceipt = null,
} = {}) {
  if (typeof agent === 'function') return agent;

  const spec = resolveTrioIndexSpec({ driverPath, env });
  let modulePromise = null;
  const receipts = [];
  const loadModule = async () => {
    if (!modulePromise) {
      modulePromise = Promise.resolve(importModule(spec)).catch((error) => {
        modulePromise = null;
        throw new AgentSeamUnavailable(`driver '${spec}' could not be imported: ${error.message}`);
      });
    }
    return modulePromise;
  };

  const resolved = async (prompt, callOpts = {}) => {
    const mod = typeof runAgent === 'function' ? null : await loadModule();
    const sharedRunAgent = typeof runAgent === 'function' ? runAgent : mod?.runAgent;
    const role = roleForTidyCall(callOpts);
    if (typeof sharedRunAgent === 'function') {
      return sharedRunAgent({
        ...callOpts,
        prompt,
        role,
        label: callOpts.label || `tidy-idy:${role}`,
        model: model || callOpts.model || undefined,
        freshContext: true,
        target,
        env: { ...env, CRUCIBLE_AGENT_LIVE: env.CRUCIBLE_AGENT_LIVE || '1' },
        log,
        onReceipt: async (receipt) => {
          receipts.push(receipt);
          if (typeof onReceipt === 'function') await onReceipt(receipt);
          if (typeof callOpts.onReceipt === 'function' && callOpts.onReceipt !== onReceipt) {
            await callOpts.onReceipt(receipt);
          }
        },
      });
    }

    // Compatibility only for existing hermetic fixtures/configured modules.
    if (typeof mod?.makeGeminiCliSeam === 'function') {
      const chosenModel = model || mod.DEFAULT_GEMINI_CLI_MODEL;
      const seam = mod.makeGeminiCliSeam({ model: chosenModel, role, log });
      return seam.agent(prompt, { ...callOpts, role });
    }
    throw new AgentSeamUnavailable(
      `driver '${spec}' exports neither runAgent nor legacy makeGeminiCliSeam()`,
    );
  };
  resolved.receipts = receipts;
  return resolved;
}

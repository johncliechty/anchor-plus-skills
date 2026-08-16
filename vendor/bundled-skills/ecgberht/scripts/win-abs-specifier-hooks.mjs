/**
 * Windows ESM resolve hook: absolute path specifiers like `C:/foo/bar.mjs`
 * are rejected by Node's default loader (`ERR_UNSUPPORTED_ESM_URL_SCHEME`,
 * protocol `c:`). Rewrite drive-letter absolute paths to `file://` URLs so
 * two-process workers that import by absolute path (e.g. T-DUR-S7) can load.
 *
 * Only rewrites Windows drive-letter absolute paths. Relative, package, and
 * already-schemed (`file:`, `node:`, `data:`) specifiers are untouched.
 */

import path from 'node:path';
import { pathToFileURL } from 'node:url';

/**
 * @param {string} specifier
 * @param {object} context
 * @param {(specifier: string, context: object) => Promise<object>} nextResolve
 */
export async function resolve(specifier, context, nextResolve) {
  if (typeof specifier === 'string' && /^[A-Za-z]:[\\/]/.test(specifier)) {
    return {
      shortCircuit: true,
      url: pathToFileURL(path.resolve(specifier)).href,
    };
  }
  return nextResolve(specifier, context);
}

/**
 * Cross-repo pytest bridge (Wave 1 BUILD CONTRACT).
 * When a wave's manifest lists Anchor-side paths, invoke
 * `python -m pytest <paths>` with cwd = Anchor root and fold into pass/fail.
 */

import { spawnSync } from 'node:child_process';
import { resolveAnchorRoot } from './wave-manifests.mjs';

/**
 * @param {string} ecgberhtRoot
 * @param {string[]} relPaths paths relative to Anchor root
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {number} exit status
 */
export function runPytestBridge(ecgberhtRoot, relPaths, env = process.env) {
  if (!relPaths || relPaths.length === 0) {
    return 0;
  }
  const anchorRoot = resolveAnchorRoot(ecgberhtRoot, env);
  if (!anchorRoot) {
    console.error(
      'pytest-bridge: Anchor root not found (set ANCHOR_REPO) but paths were listed',
    );
    return 1;
  }
  const r = spawnSync(env.PYTHON || 'python', ['-m', 'pytest', ...relPaths], {
    cwd: anchorRoot,
    stdio: 'inherit',
    windowsHide: true,
    shell: false,
    env,
  });
  return typeof r.status === 'number' ? r.status : 1;
}

// engine/launch/opener.mjs — Wave 5: environment-adaptive openers.
//
// The carried "investigator-tile" finding asks a fair question: if the panel is
// "identical" on both launch paths, what happens to the things that are
// inherently environmental — opening a browser, and (Wave 7) opening a terminal?
//
// The answer this module encodes: ONE LAUNCH SPEC, MANY OPENERS.
//
//   identical  = the machine envelope, the finding rendering, the archive layout,
//                and the Apply semantics. These have exactly one implementation
//                and are asserted equal by the parity test.
//   adaptive   = the ACT of opening. A standalone run shells out to the OS
//                browser opener; a run hosted inside Anchor hands the same URL to
//                Anchor's surface to open. Same spec, same URL, same server —
//                different final verb.
//
// What this is NOT: a second code path, and not a hard Anchor dependency in the
// panel. The 'anchor' opener does not import Anchor; it RETURNS the spec for
// Anchor's caller to execute, so the tool never depends on Anchor being there.

import { spawn as nodeSpawn } from 'node:child_process';

export const ENVIRONMENT = Object.freeze({
  STANDALONE: 'standalone',
  ANCHOR: 'anchor',
  NONE: 'none',
});

/**
 * The launch spec — one shape, produced identically on every path.
 *
 * @param {{url: string, nonceFile?: string|null, identity: object, runNumber?: number|null}} opts
 */
export function panelLaunchSpec({ url, nonceFile = null, identity, runNumber = null }) {
  return {
    kind: 'open-url',
    url,
    /** Single-use: the first GET redeems it and it is invalid thereafter. */
    singleUse: true,
    nonceFile,
    project: { name: identity.name, path: identity.path },
    runNumber,
    note: 'one launch spec; the opener that executes it is environment-appropriate (OS browser when standalone, Anchor\'s surface when hosted) — never a second panel or launch code path',
  };
}

/**
 * Execute a launch spec in the given environment.
 *
 * @param {{spec: object, environment?: string, spawn?: Function, platform?: string, log?: Function}} opts
 * @returns {Promise<{opened: boolean, by: string, spec: object, error?: string}>}
 */
export async function openPanel({ spec, environment = ENVIRONMENT.STANDALONE, spawn = nodeSpawn, platform = process.platform, log = () => {} } = {}) {
  if (environment === ENVIRONMENT.NONE) {
    return { opened: false, by: 'none', spec, note: 'headless/CI launch — the bootstrap URL is returned unopened and remains single-use' };
  }
  if (environment === ENVIRONMENT.ANCHOR) {
    // Anchor's button opens it in Anchor's own surface. The tool does not import
    // Anchor to do that; it hands the spec back.
    return { opened: false, by: 'anchor', spec, handoff: true, note: "the Anchor caller opens this URL in Anchor's surface — the tool neither hosts nor duplicates that step" };
  }

  try {
    const { command, args, opts } = browserCommand(spec.url, platform);
    const child = spawn(command, args, { detached: true, stdio: 'ignore', ...opts });
    if (child && typeof child.unref === 'function') child.unref();
    // The URL carries only the single-use NONCE, so even a shell history entry or
    // a process-list snapshot yields nothing once the panel has loaded.
    log('panel opened in the default browser');
    return { opened: true, by: 'browser', spec };
  } catch (err) {
    return { opened: false, by: 'browser', spec, error: err && err.message };
  }
}

/** The per-platform browser-open command. Split out so a test can assert it. */
export function browserCommand(url, platform = process.platform) {
  if (platform === 'win32') {
    // `start` is a cmd builtin; the empty title argument is required so a quoted
    // URL is not consumed as the window title.
    return { command: 'cmd', args: ['/c', 'start', '', url], opts: { windowsHide: true } };
  }
  if (platform === 'darwin') return { command: 'open', args: [url], opts: {} };
  return { command: 'xdg-open', args: [url], opts: {} };
}

export default { openPanel, panelLaunchSpec, browserCommand, ENVIRONMENT };

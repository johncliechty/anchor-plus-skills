// engine/launch/anchor-caller.mjs — Wave 5: the THIN Anchor caller.
//
// Anchor's Tidy-Idy button does exactly two things:
//
//   1. DISPATCH the tool's own entry point (`bin/tidy-idy.mjs <folder>`) through
//      job_runner, so the run is headless-in-Anchor with live state and a
//      resource claim on the folder;
//   2. OPEN the panel URL that run prints.
//
// It adds no launch logic, no archive logic and no panel logic. Everything the
// button gets, a bare `tidy-idy <folder>` from a terminal already produced — the
// parity test asserts that by running both and comparing the envelope and the
// archive layout.
//
// This module contains NO Anchor import. It builds a job SPEC and hands it to an
// injected `jobRunner` adapter, so the tool can be tested (and can run) with
// Anchor absent, which is the whole point of Amendment D. The adapter's shape is
// taken from job_runner.py's ACTUAL source; the written contract, with the source
// facts it rests on, is docs/anchor-job-runner-integration-contract.md.
//
// SOURCE FACTS THAT SHAPE THIS FILE (job_runner.py, read 2026-07-21):
//
//   • `launch_guarded(lane, project_id, folder_path, ..., command=None)` is the
//     guarded spawn. When `command` is an argv list it IS the launched command
//     verbatim — backend/model resolution is bypassed. A tidy run is deterministic
//     local code, so it dispatches on the `command` seam, never as a model lane.
//   • The FOLDER-level resource claim (`_FOLDER_BUILD`) is taken ONLY when
//     `lane == BUILD_LANE` ("build"). A job on a bespoke `tidy` lane would get
//     within-project same-lane serialization and NO folder claim — i.e. a Foreman
//     build would not queue behind it. So the button dispatches on the build lane
//     to acquire the real claim, and stamps `job_type: 'tidy'` for the UI.
//   • There is NO completion CALLBACK. `_finalize` writes a terminal status onto
//     the durable record; callers observe completion by polling `load_record` /
//     `long_poll` and reading the durable log. This caller therefore watches for
//     the run's own `panel-ready` line rather than waiting to be called back.
//   • The run index is per-tool: Gandalf's index is its own file, and a tidy run
//     writes ONLY the tool's `runs-tidy/index.json`. No row of Gandalf's is
//     touched, which is what keeps Gandalf's suite a no-behavior-change
//     regression suite.

import path from 'node:path';
import fsp from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

/** job_runner's folder-claiming lane. Source: job_runner.BUILD_LANE. */
export const FOLDER_CLAIM_LANE = 'build';
/** The namespaced job type stamped on the record (UI/History), not a lane. */
export const TIDY_JOB_TYPE = 'tidy';

/** `bin/tidy-idy.mjs` — the one entry point every caller shares. */
export function tidyIdyEntryPoint() {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'bin', 'tidy-idy.mjs');
}

/**
 * Build the job spec for a button-dispatched tidy run.
 *
 * @param {{rootPath: string, projectId?: string|null, nonceFile?: string|null,
 *          node?: string, entry?: string|null, lane?: string, extraArgs?: string[]}} opts
 */
export function buildTidyJobSpec({
  rootPath,
  projectId = null,
  nonceFile = null,
  node = process.execPath,
  entry = null,
  lane = FOLDER_CLAIM_LANE,
  extraArgs = [],
} = {}) {
  const root = path.resolve(rootPath);
  const command = [
    node,
    entry || tidyIdyEntryPoint(),
    root,
    // The Anchor surface opens the URL; the run must not also shell out to a
    // browser on the server's desktop.
    '--environment=anchor',
    '--json',
    ...(nonceFile ? [`--nonce-file=${nonceFile}`] : []),
    ...extraArgs,
  ];
  return {
    lane,
    project_id: projectId,
    folder_path: root,
    cwd: root,
    /** The control-plane argv seam: deterministic local code, no model backend. */
    command,
    gated: false,
    job_type: TIDY_JOB_TYPE,
    /**
     * Documented consequence of the lane choice, carried on the spec so a reader
     * of a job record can see WHY a hygiene run is on the build lane.
     */
    resourceClaim: lane === FOLDER_CLAIM_LANE
      ? 'folder-build — job_runner claims the folder for this job, so a Foreman/Gandalf build for ANY project sharing this folder queues behind it'
      : 'none — job_runner takes a folder-level claim only on the build lane; the tool\'s own lockfile remains the authority',
  };
}

/**
 * Dispatch a tidy run through job_runner and return the panel handoff.
 *
 * @param {{rootPath: string, jobRunner: object, projectId?: string|null,
 *          waitForPanelMs?: number, log?: Function, fs?: object}} opts
 *   `jobRunner` must provide: launchGuarded(spec) -> record,
 *   and (optionally) loadRecord(jobId) / readLog(jobId) for the panel wait.
 */
export async function dispatchTidy({
  rootPath,
  jobRunner,
  projectId = null,
  nonceFile = null,
  waitForPanelMs = 120000,
  pollMs = 50,
  log = () => {},
  now = () => Date.now(),
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
} = {}) {
  if (!jobRunner || typeof jobRunner.launchGuarded !== 'function') {
    throw new Error('dispatchTidy needs a jobRunner adapter exposing launchGuarded(spec) — the tool never imports Anchor directly');
  }
  const spec = buildTidyJobSpec({ rootPath, projectId, nonceFile });
  const record = await jobRunner.launchGuarded(spec);
  log(`tidy run dispatched as job ${record && record.job_id} (claim: ${spec.resourceClaim})`);

  // job_runner has no completion callback (source fact above): observe the run
  // through its durable log, exactly as Anchor's other consumers do.
  const ready = await waitForPanelReady({ jobRunner, jobId: record && record.job_id, waitForPanelMs, pollMs, now, sleep });

  // THE NONCE NEVER TRANSITS THE DURABLE LOG. job_runner streams a job's stdout
  // into a persistent log file, so the run prints only the panel's BASE url and
  // the path of the 0600 bootstrap file; the single-use nonce is read from that
  // file here and the server unlinks it on redemption.
  const bootstrap = ready && ready.bootstrapFile ? await readBootstrapFile(ready.bootstrapFile) : null;
  const panel = ready ? { ...ready, bootstrapUrl: bootstrap ? bootstrap.url : null } : null;

  return {
    spec,
    record,
    panel,
    /**
     * The button's SECOND and LAST act. It is a handoff, not an implementation:
     * the URL belongs to the tool's own server and the page it serves is the
     * tool's own panel.
     */
    open: panel && panel.bootstrapUrl ? { kind: 'open-url', url: panel.bootstrapUrl, singleUse: true } : null,
    contributedLaunchLogic: false,
    contributedArchiveLogic: false,
    contributedPanelLogic: false,
  };
}

/** Poll the job's durable log for the run's own `panel-ready` line. */
export async function waitForPanelReady({ jobRunner, jobId, waitForPanelMs = 120000, pollMs = 50, now = () => Date.now(), sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  if (!jobId || typeof jobRunner.readLog !== 'function') return null;
  const deadline = now() + waitForPanelMs;
  for (;;) {
    const text = await jobRunner.readLog(jobId);
    const found = parsePanelReady(String(text || ''));
    if (found) return found;
    if (typeof jobRunner.loadRecord === 'function') {
      const rec = await jobRunner.loadRecord(jobId);
      if (rec && rec.status && rec.status !== 'running') {
        // Terminal without a panel line: the run failed or ran headless. Say so
        // rather than spinning to the deadline.
        return null;
      }
    }
    if (now() >= deadline) return null;
    await sleep(pollMs);
  }
}

/** The single machine-readable line the CLI prints when its panel is up. */
export const PANEL_READY_EVENT = 'panel-ready';

export function parsePanelReady(text) {
  for (const line of String(text).split(/\r?\n/)) {
    const t = line.trim();
    if (!t.startsWith('{')) continue;
    try {
      const parsed = JSON.parse(t);
      if (parsed && parsed.event === PANEL_READY_EVENT) return parsed;
    } catch { /* not our line */ }
  }
  return null;
}

/** Read the 0600 bootstrap file the run wrote. Returns {url} or null. */
export async function readBootstrapFile(file, { fs = fsp } = {}) {
  try {
    const parsed = JSON.parse(String(await fs.readFile(file, 'utf8')));
    return parsed && parsed.url ? parsed : null;
  } catch {
    // Already redeemed (the server unlinks it) or never written. Either way the
    // honest answer is "no bootstrap URL available", never a guess.
    return null;
  }
}

/**
 * Is this root inside an Anchor-managed workspace? Marker-based and cheap; a
 * false answer costs a standalone run nothing.
 */
export async function detectAnchorWorkspace({ rootPath, fs = fsp, env = process.env } = {}) {
  if (env && env.ANCHOR_DATA_DIR) return { present: true, via: 'ANCHOR_DATA_DIR' };
  let dir = path.resolve(rootPath);
  for (;;) {
    try {
      const st = await fs.stat(path.join(dir, '.anchor'));
      if (st.isDirectory()) return { present: true, via: path.join(dir, '.anchor') };
    } catch { /* keep walking up */ }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return { present: false, via: null };
}

/**
 * The SYMMETRIC half of the cross-agent lock authority: a standalone CLI run on
 * an Anchor-managed folder registers a best-effort job_runner resource claim, so
 * it is not invisible to Anchor's launchers.
 *
 * BEST-EFFORT IS LOAD-BEARING. Every failure here is swallowed and reported, and
 * none of them can fail the run: a standalone run's correctness rests on the
 * tool's OWN lockfile, which was already taken before this was ever called.
 */
export async function registerResourceClaimBestEffort({ rootPath, jobRunner = null, projectId = null, runId = null, log = () => {}, fs = fsp, env = process.env } = {}) {
  const workspace = await detectAnchorWorkspace({ rootPath, fs, env });
  if (!workspace.present) {
    return { claimed: false, reason: 'not an Anchor-managed workspace — nothing to register with, and nothing depends on it' };
  }
  if (!jobRunner || typeof jobRunner.registerClaim !== 'function') {
    return { claimed: false, workspace, reason: 'Anchor workspace detected but no job_runner adapter is reachable from this process — the tool\'s own lockfile still holds the root' };
  }
  try {
    const claim = await jobRunner.registerClaim({
      lane: FOLDER_CLAIM_LANE,
      project_id: projectId,
      folder_path: path.resolve(rootPath),
      job_type: TIDY_JOB_TYPE,
      run_id: runId,
    });
    log('best-effort job_runner resource claim registered for this standalone run');
    return { claimed: true, workspace, claim };
  } catch (err) {
    return { claimed: false, workspace, reason: `claim registration failed (best-effort, run unaffected): ${err && err.message}` };
  }
}

export default {
  buildTidyJobSpec, dispatchTidy, waitForPanelReady, parsePanelReady, readBootstrapFile,
  detectAnchorWorkspace, registerResourceClaimBestEffort, tidyIdyEntryPoint,
  FOLDER_CLAIM_LANE, TIDY_JOB_TYPE, PANEL_READY_EVENT,
};

// engine/launch/launch.mjs — Wave 5: THE canonical run-and-open-panel entry point.
//
// One function. Every caller reaches it:
//
//   `tidy-idy <folder>` from a terminal   → bin/tidy-idy.mjs → tidyIdy()
//   cowork / another agent                → bin/tidy-idy.mjs → tidyIdy()
//   Anchor's Tidy-Idy button              → job_runner dispatches
//                                           bin/tidy-idy.mjs → tidyIdy()
//
// There is no second launch path, no second archive writer, and no second panel
// server. Anchor's button is a DISPATCHER and a URL OPENER; everything it gets,
// the bare CLI already produced. The parity test asserts that by running both
// over the same folder and comparing the machine envelope and archive layout.
//
// ORDER MATTERS, and each step is here for a stated reason:
//
//   1. LOCK FIRST. Before any analysis, because the lock is what makes a
//      standalone run and an Anchor-dispatched run over one root contend — and
//      that contention must not depend on job_runner having been consulted.
//   2. COST GATE SECOND. It decides the exclusion set and possibly the mode, so
//      it has to run before the context is built. It never blocks (see
//      cost-gate.mjs).
//   3. PIPELINE. Read-only. Writes nothing outside reportDir.
//   4. ARCHIVE. The launcher's write, after the sweep, never overwriting.
//   5. PANEL. The tool's own server, and the lock is released when IT dies —
//      so the lock's lifetime is the panel's lifetime, which is what makes
//      "Apply later from the panel" safe.
//
// ZERO ANCHOR DEPENDENCY means precisely this: nothing above imports Anchor,
// and none of steps 1–5 changes behaviour or correctness when Anchor is absent.
// It does NOT mean mutual blindness — step 5b registers a best-effort job_runner
// resource claim when an Anchor workspace is detected, and Anchor's launchers
// consult this tool's lockfile (engine/launch/lock-authority.mjs).

import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn as nodeSpawn } from 'node:child_process';

import { createContext, reportDirFor } from '../context.mjs';
import { runPipeline, runPipelineWithContext } from '../pipeline.mjs';
import { STAGES } from '../stages/index.mjs';
import { loadConfig, ConfigParseError } from '../config.mjs';
import { makeProtection } from '../protection.mjs';
import { acquireLock, LOCK_REFUSAL } from '../apply/lock.mjs';

import { projectIdentity } from './identity.mjs';
import { evaluateCostGate } from './cost-gate.mjs';
import { openVerdictCache } from './verdict-cache.mjs';
import { archiveRun, readRunIndex } from './archive.mjs';
import { servePanel, CLOSE_REASON } from './panel-server.mjs';
import { openPanel, panelLaunchSpec, ENVIRONMENT } from './opener.mjs';
import { registerResourceClaimBestEffort } from './anchor-caller.mjs';
import { makeInvestigateHook, investigatorSlotDescriptor } from './investigator.mjs';
import { writeStatus, readStatus, PHASE } from './run-status.mjs';
import { serveRunStatus } from './status-server.mjs';

export const LAUNCH_STATUS = Object.freeze({
  OK: 'ok',
  REFUSED: 'refused',
  /** A live run already holds this root — status/panel URLs are returned for re-open. */
  ALREADY_RUNNING: 'already-running',
});

/**
 * Run tidy-idy over a folder and (optionally) open its Triage Panel.
 *
 * @param {object} opts
 * @returns {Promise<object>} the launch result
 */
export async function tidyIdy(opts = {}) {
  const {
    rootPath,
    environment = ENVIRONMENT.STANDALONE,
    open = true,
    serve = true,
    stages = STAGES,
    log = () => {},
    now = () => new Date(),
    fs = fsp,
    jobRunner = null,
    projectId = null,
    nonceFile = null,
    port = 0,
    idleTimeoutMs,
    heartbeatGapMs,
    costGateEnabled = true,
    verdictCacheEnabled = true,
    spawn,
    platform,
    /** Optional (ev) => void — e.g. emit early status-ready JSON for job logs. */
    onEvent = null,
    ...pipelineOpts
  } = opts;

  if (!rootPath) throw new Error('tidyIdy needs a rootPath — the folder IS the project');
  const root = path.resolve(rootPath);

  const st = await fs.stat(root).catch(() => null);
  if (!st || !st.isDirectory()) {
    return {
      status: LAUNCH_STATUS.REFUSED,
      code: 'NOT_A_DIRECTORY',
      rootPath: root,
      message: `'${root}' is not a directory — tidy-idy runs on a folder, and it will not guess which one you meant`,
    };
  }

  const reportDir = pipelineOpts.reportDir ? path.resolve(pipelineOpts.reportDir) : reportDirFor(root);
  const nameGuess = path.basename(root);

  // ---- 0. Re-open an already-live run (second click) ----------------------
  // If another tidy process holds the lock, do NOT start a second pass. Hand
  // back the status page and/or panel URL so the caller can focus the GUI.
  const prior = await readStatus(reportDir, { fs });
  const lockProbe = await acquireLock({ reportDir, purpose: 'run', jobId: pipelineOpts.runId || null, fs, now });
  if (!lockProbe.ok) {
    const st = prior || {};
    return {
      status: LAUNCH_STATUS.ALREADY_RUNNING,
      code: lockProbe.code || LOCK_REFUSAL.HELD,
      rootPath: root,
      holder: lockProbe.holder || null,
      message: lockProbe.message,
      statusUrl: st.statusUrl || null,
      panelBaseUrl: st.panelBaseUrl || null,
      openUrl: st.openUrl || st.panelBaseUrl || st.statusUrl || null,
      phase: st.phase || PHASE.SCANNING,
      identity: { name: st.projectName || nameGuess, path: root },
    };
  }
  const lock = lockProbe;

  let released = false;
  const releaseLock = async () => {
    if (released) return;
    released = true;
    await lock.release().catch(() => {});
  };

  // Status server + first browser open — BEFORE the long pipeline so the human
  // always sees progress (standalone and Anchor status-tab both use this).
  let statusServer = null;
  const setPhase = async (phase, message, extra = {}) => {
    const patch = {
      phase,
      message,
      rootPath: root,
      projectName: nameGuess,
      pid: process.pid,
      ...extra,
    };
    if (statusServer) {
      patch.statusPort = statusServer.port;
      patch.statusUrl = statusServer.url;
    }
    return writeStatus(reportDir, patch, { fs, now });
  };

  try {
    statusServer = await serveRunStatus({ reportDir, fs, log, title: `Tidy-Idy — ${nameGuess}` });
    await setPhase(PHASE.STARTING, 'Locked the project and opened the status page…', {
      step: 'start',
      stepLabel: 'Starting',
      forceNewRun: true,
      startedAt: now().toISOString(),
      findings: null,
      runId: null,
      runNumber: null,
      openUrl: null,
      panelBaseUrl: null,
      bootstrapFile: null,
      error: null,
    });

    // Emit IMMEDIATELY so Anchor's job log / thin caller can hand the browser a
    // status URL before the (long) pipeline runs. Previously status-ready was
    // only printed after the full scan, so the UI sat at 2% for the whole job.
    if (typeof onEvent === 'function') {
      try {
        await onEvent({
          event: 'status-ready',
          statusUrl: statusServer.url,
          phase: PHASE.STARTING,
          progress: 2,
          project: { name: nameGuess, path: root },
        });
      } catch { /* non-fatal */ }
    }

    // Standalone: open the status page immediately (OS browser). Anchor opens
    // its own tab and polls; still return statusUrl for the thin caller.
    let statusOpened = null;
    if (open && environment === ENVIRONMENT.STANDALONE) {
      statusOpened = await openPanel({
        spec: panelLaunchSpec({
          url: statusServer.url,
          identity: { name: nameGuess, path: root },
          runNumber: null,
        }),
        environment: ENVIRONMENT.STANDALONE,
        log,
        ...(spawn ? { spawn } : {}),
        ...(platform ? { platform } : {}),
      });
    }

    // ---- 2. the cost gate ------------------------------------------------
    let config = {};
    let configError = null;
    try {
      config = (await loadConfig(root, {})).config;
    } catch (err) {
      // A malformed config must not be silently ignored here either: the gate is
      // skipped and the PIPELINE produces the failed-config-stage envelope, which
      // is the one place that refusal is defined.
      if (!(err instanceof ConfigParseError)) throw err;
      configError = err;
    }

    let costGate = null;
    if (configError) {
      costGate = { ran: false, blocked: false, gated: false, note: `cost gate skipped: ${configError.message}` };
    } else if (!costGateEnabled) {
      costGate = { ran: false, blocked: false, gated: false, note: 'cost gate disabled by the caller (a confirmed full-scope re-run from the panel does exactly this)' };
    } else {
      await setPhase(PHASE.SCANNING, 'Running the pre-scan cost gate…', {
        step: 'cost-gate',
        stepLabel: 'Cost gate',
      });
      costGate = await evaluateCostGate({
        rootPath: root,
        config,
        protection: makeProtection(config),
        reportDir,
        fs,
        mode: pipelineOpts.mode || null,
      });
    }

    const degraded = Boolean(costGate && costGate.gated);
    const configOverlay = degraded
      ? { exclude: { patterns: costGate.degradation.exclusionsApplied } }
      : null;
    const forcedMode = degraded && costGate.degradation.forcedMode ? costGate.degradation.forcedMode : null;
    if (degraded) {
      log(`cost gate: ${costGate.banner.message}`);
    }

    // ---- 3. the run -------------------------------------------------------
    const launchAnnotation = {
      environment,
      anchor: { projectId, dispatched: environment === ENVIRONMENT.ANCHOR },
    };

    await setPhase(PHASE.ANALYZING, degraded
      ? 'Analyzing (cost-gated / heuristic narrowing)…'
      : 'Analyzing the folder (this can take a minute on large trees)…', {
      step: 'topology',
      stepLabel: 'Starting analysis',
    });

    const onProgress = async ({ step, message, stepLabel, stepIndex, stepTotal, findingsSoFar }) => {
      await setPhase(PHASE.ANALYZING, message || `Running ${step}…`, {
        step,
        stepLabel: stepLabel || step,
        stepIndex: stepIndex ?? null,
        stepTotal: stepTotal ?? null,
        ...(findingsSoFar != null ? { findings: findingsSoFar } : {}),
      });
    };

    let ctx = null;
    let envelope;
    let cache = null;
    try {
      ctx = await createContext({
        ...pipelineOpts,
        rootPath: root,
        reportDir,
        log,
        now,
        configOverlay,
        ...(forcedMode ? { mode: forcedMode } : {}),
        costGate,
        launch: launchAnnotation,
      });
    } catch {
      ctx = null; // runPipeline below renders the refusal as a failed stage
    }

    if (ctx) {
      cache = await openVerdictCache({
        reportDir,
        rulesetVersion: ctx.ruleset.version,
        fs,
        now,
        enabled: verdictCacheEnabled,
      });
      ctx.verdictCache = cache;
      envelope = await runPipelineWithContext(ctx, { stages, onProgress });
      await cache.save();
    } else {
      envelope = await runPipeline({
        ...pipelineOpts,
        rootPath: root,
        reportDir,
        log,
        now,
        configOverlay,
        costGate,
        stages,
        onProgress,
      });
    }

    const identity = envelope.identity || projectIdentity({ rootPath: root, git: ctx ? ctx.git : null });
    await setPhase(PHASE.ARCHIVING, `Analysis done — ${(envelope.findings || []).length} finding(s). Writing the report…`, {
      projectName: identity.name,
      runId: envelope.runId,
      findings: (envelope.findings || []).length,
      step: 'archive',
      stepLabel: 'Writing report',
    });

    // ---- 4. the archive ----------------------------------------------------
    const archive = await archiveRun({
      rootPath: root,
      reportDir,
      envelope,
      identity,
      costGate,
      verdictCache: cache ? cache.summary() : null,
      launchedBy: environment,
      fs,
      now,
    });
    log(`run ${archive.runNumber} archived at ${archive.dir}`);

    // ---- 5. the panel ------------------------------------------------------
    let panel = null;
    let opened = statusOpened;
    if (serve) {
      const runIndex = await readRunIndex(reportDir, { fs });
      panel = await servePanel({
        envelope,
        identity,
        runNumber: archive.runNumber,
        archive: { runNumber: archive.runNumber, dir: archive.dir, files: archive.files },
        runIndex,
        costGate,
        // ---- what the Wave-6 control plane needs to act, not just render ----
        rootPath: root,
        reportDir,
        // The LIVE git handle, so staleness is a real `rev-parse HEAD` rather
        // than a claim about one, and so Apply compiles against this repository.
        git: ctx ? ctx.git : null,
        // The panel's Apply borrows the lock this launcher already holds; see
        // engine/apply/executor.mjs. Re-acquiring it would deadlock the tool
        // against itself.
        lock,
        onRescan: makeRescanHook({ root, log, spawn, closePanel: async () => { if (panel) await panel.close(CLOSE_REASON.EXPLICIT); } }),
        // ---- the Wave-7 investigator terminal ------------------------------
        // The tile posts here; the hook builds the per-run briefing (skill
        // inlined when unresolvable in THIS environment) and opens a terminal in
        // the project cwd, or hands the spec back when Anchor hosts the surface.
        onInvestigate: makeInvestigateHook({
          rootPath: root,
          runDir: archive.dir,
          envelope,
          identity,
          runNumber: archive.runNumber,
          config,
          environment,
          ...(spawn ? { spawn } : {}),
          log,
        }),
        investigator: investigatorSlotDescriptor({ config, archive }),
        log,
        port,
        nonceFile,
        fs,
        now,
        ...(Number.isInteger(idleTimeoutMs) ? { idleTimeoutMs } : {}),
        ...(Number.isInteger(heartbeatGapMs) ? { heartbeatGapMs } : {}),
        // THE LOCK'S LIFETIME IS THE PANEL'S LIFETIME. Every way the server can
        // end — explicit close, idle timeout, heartbeat gap, caller close — runs
        // this exactly once. A SIGKILL runs none of them, which is what the
        // stale-PID-aware lock exists for.
        onClose: async () => {
          await writeStatus(reportDir, {
            phase: PHASE.DONE,
            message: 'Panel closed — project lock released.',
            openUrl: null,
          }, { fs, now }).catch(() => {});
          if (statusServer) await statusServer.close().catch(() => {});
          await releaseLock();
        },
      });

      await setPhase(PHASE.PANEL_READY, 'Triage Panel is ready.', {
        projectName: identity.name,
        runId: envelope.runId,
        runNumber: archive.runNumber,
        findings: (envelope.findings || []).length,
        panelBaseUrl: panel.url,
        openUrl: panel.bootstrapUrl,
        bootstrapFile: panel.nonceFile,
        step: 'panel',
        stepLabel: 'Panel ready',
        progress: 100,
      });

      // Standalone: status page already open and will redirect to bootstrap via
      // poll. Do NOT open a second browser window to the bootstrap URL.
      // Anchor: thin caller navigates its status tab.
      opened = {
        opened: Boolean(statusOpened && statusOpened.opened),
        by: environment === ENVIRONMENT.STANDALONE ? 'status-page' : 'anchor',
        spec: panelLaunchSpec({ url: panel.bootstrapUrl, nonceFile: panel.nonceFile, identity, runNumber: archive.runNumber }),
        note: 'status page redirects to the single-use bootstrap URL when phase=panel-ready',
      };
    } else {
      await setPhase(PHASE.DONE, 'Run finished (no panel served).', {
        findings: (envelope.findings || []).length,
        runId: envelope.runId,
      });
      if (statusServer) await statusServer.close().catch(() => {});
      await releaseLock();
    }

    // ---- 5b. the symmetric, best-effort Anchor claim -----------------------
    // Never load-bearing: the tool's own lock (step 1) already holds this root.
    const claim = await registerResourceClaimBestEffort({
      rootPath: root, jobRunner, projectId, runId: envelope.runId, log, fs,
    });

    return {
      status: LAUNCH_STATUS.OK,
      rootPath: root,
      reportDir,
      identity,
      envelope,
      costGate,
      verdictCache: cache ? cache.summary() : null,
      archive,
      runNumber: archive.runNumber,
      statusUrl: statusServer ? statusServer.url : null,
      panel: panel
        ? {
          url: panel.url,
          bootstrapUrl: panel.bootstrapUrl,
          nonceFile: panel.nonceFile,
          port: panel.port,
          runId: panel.runId,
        }
        : null,
      opened,
      anchorClaim: claim,
      lock: { held: Boolean(serve), stolenFrom: lock.stolenFrom || null },
      /** Close the panel and release the lock. Idempotent. */
      async close(reason) {
        if (panel) await panel.close(reason);
        if (statusServer) await statusServer.close().catch(() => {});
        await releaseLock();
      },
      /** Test/host handle onto the live server (never serialised). */
      server: panel,
      statusServer,
    };
  } catch (err) {
    await writeStatus(reportDir, {
      phase: PHASE.FAILED,
      message: `Run failed: ${err && err.message}`,
      error: err && err.message,
    }, { fs, now }).catch(() => {});
    if (statusServer) await statusServer.close().catch(() => {});
    await releaseLock();
    throw err;
  }
}

/** `bin/tidy-idy.mjs`, resolved from this module rather than from a cwd. */
export const CLI_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'bin', 'tidy-idy.mjs');

/**
 * The panel's one-click re-scan (and the cost-gate banner's confirm-full-run,
 * which is the same act with the gate turned off).
 *
 * ORDER IS THE WHOLE DESIGN. The current panel holds the project lock for its
 * own lifetime, so a fresh run cannot start while it lives — a re-scan that
 * merely spawned would be refused by the tool's own lock, which is correct
 * behaviour and a useless button. So the hook CLOSES THIS PANEL FIRST (which
 * releases the lock through the same onClose path every other exit uses) and
 * only then spawns the successor, detached, which takes the lock cleanly and
 * opens its own panel with its own freshly minted token.
 *
 * `spawn` is injectable so a test can assert the command without launching one.
 */
export function makeRescanHook({ root, log = () => {}, spawn = null, closePanel = null, cliPath = CLI_PATH } = {}) {
  const launcher = spawn || nodeSpawn;
  return async ({ costGateEnabled = true } = {}) => {
    const command = [
      process.execPath,
      cliPath,
      root,
      ...(costGateEnabled ? [] : ['--no-cost-gate']),
    ];
    let spawned = false;
    let error = null;
    try {
      if (closePanel) await closePanel();
      const child = launcher(command[0], command.slice(1), { detached: true, stdio: 'ignore', cwd: root });
      if (child && typeof child.unref === 'function') child.unref();
      spawned = true;
    } catch (err) {
      error = err && err.message;
    }
    log(`re-scan requested from the panel (${costGateEnabled ? 'same scope' : 'FULL scope — cost gate confirmed off'})`);
    return {
      command,
      spawned,
      ...(error ? { error } : {}),
      message: spawned
        ? 'this panel has closed and released the project lock; a fresh run is starting and will open its own panel with a newly minted token'
        : `the successor run could not be started (${error}) — run \`tidy-idy ${root}\` yourself`,
    };
  };
}

export default { tidyIdy, makeRescanHook, LAUNCH_STATUS, CLI_PATH };

import { spawn as nodeSpawn, spawnSync as nodeSpawnSync } from 'node:child_process';

function errorMessage(error) {
  return String(error?.message ?? error ?? '').slice(0, 500);
}

/**
 * Spawn one subscription CLI process and settle after `close` (or after a grace
 * reap when `shouldCompleteEarly` observes a complete terminal protocol frame
 * and the CLI lingers without exiting). Also supports a configurable stream-idle
 * watchdog (`idleTimeoutMs`, reset on any stdout/stderr chunk) and destroys pipe
 * handles on finish so inherited Windows handles never hold the event loop open.
 */
export function runCloseBoundProcess({
  command,
  args = [],
  options = {},
  input = null,
  signal = null,
  timeoutMs = 0,
  idleTimeoutMs = 0,
  shouldCompleteEarly = null,
  earlyGraceMs = 1500,
  label = '(unlabeled)',
  log = () => {},
  spawnImpl = nodeSpawn,
  spawnSyncImpl = nodeSpawnSync,
  platform = process.platform,
  killImpl = process.kill.bind(process),
} = {}) {
  if (signal?.aborted) {
    return Promise.resolve({
      code: null, stdout: '', stderr: '', terminal: 'aborted',
      error: 'seat aborted before spawn', kill_status: null, spawned: false,
    });
  }

  return new Promise((resolve) => {
    let child;
    try {
      child = spawnImpl(command, args, {
        ...options,
        windowsHide: options.windowsHide ?? true,
        shell: options.shell ?? false,
        detached: platform === 'win32' ? (options.detached ?? false) : true,
      });
    } catch (error) {
      resolve({
        code: null, stdout: '', stderr: '', terminal: 'spawn_error',
        error: errorMessage(error), kill_status: null, spawned: false,
      });
      return;
    }
    if (!child || typeof child.on !== 'function') {
      resolve({
        code: null, stdout: '', stderr: '', terminal: 'spawn_error',
        error: 'spawn returned no child process', kill_status: null, spawned: false,
      });
      return;
    }

    let stdout = '';
    let stderr = '';
    let spawnError = null;
    let terminalCause = null;
    let killStatus = null;
    let killStarted = false;
    let finalized = false;
    let closed = false;
    let earlyCompleted = false;
    let reapedAfterResult = false;
    let timer = null;
    let idleTimer = null;
    let earlyTimer = null;
    let closeGuardTimer = null;

    const destroyStreams = () => {
      try { child.stdin?.destroy?.(); } catch { /* best effort */ }
      try { child.stdout?.destroy?.(); } catch { /* best effort */ }
      try { child.stderr?.destroy?.(); } catch { /* best effort */ }
      try { child.unref?.(); } catch { /* best effort */ }
    };

    const armCloseGuard = (fallbackCode = null) => {
      if (closeGuardTimer || finalized) return;
      closeGuardTimer = setTimeout(() => {
        if (!finalized) {
          destroyStreams();
          finish(child.exitCode ?? fallbackCode);
        }
      }, 1500);
      if (typeof closeGuardTimer.unref === 'function') closeGuardTimer.unref();
    };

    const killTreeOnce = () => {
      if (killStarted || closed) return;
      killStarted = true;
      const pid = Number(child?.pid);
      if (!Number.isInteger(pid) || pid <= 0) {
        killStatus = 'kill_failed';
        return;
      }
      if (child.exitCode != null || child.signalCode != null) {
        killStatus = 'already_closed';
        return;
      }
      try {
        if (platform === 'win32') {
          const killed = spawnSyncImpl(
            'taskkill', ['/pid', String(pid), '/t', '/f'],
            { shell: false, windowsHide: true, encoding: 'utf8' },
          );
          killStatus = killed?.status === 0 ? 'killed' : 'kill_failed';
        } else {
          killImpl(-pid, 'SIGKILL');
          killStatus = 'killed';
        }
      } catch (error) {
        killStatus = error?.code === 'ESRCH' ? 'already_closed' : 'kill_failed';
      }
    };

    const chooseTerminal = (cause) => {
      if (terminalCause || finalized) return;
      if (earlyCompleted && (cause === 'timeout' || cause === 'idle_timeout')) {
        reapedAfterResult = true;
        killTreeOnce();
        armCloseGuard(0);
        return;
      }
      terminalCause = cause;
      log(`!! ${label}: ${cause} - killing subscription child tree`);
      killTreeOnce();
      armCloseGuard(null);
    };

    const resetIdleTimer = () => {
      if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
      }
      if (finalized || terminalCause || earlyCompleted) return;
      if (Number.isFinite(idleTimeoutMs) && idleTimeoutMs > 0) {
        idleTimer = setTimeout(() => chooseTerminal('timeout'), idleTimeoutMs);
        if (typeof idleTimer.unref === 'function') idleTimer.unref();
      }
    };

    const checkEarlyCompletion = () => {
      if (earlyCompleted || finalized || terminalCause || typeof shouldCompleteEarly !== 'function') return;
      let complete = false;
      try { complete = Boolean(shouldCompleteEarly(stdout, stderr)); } catch { complete = false; }
      if (!complete) return;
      earlyCompleted = true;
      if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
      }
      const grace = Number.isFinite(earlyGraceMs) && earlyGraceMs >= 0 ? earlyGraceMs : 1500;
      earlyTimer = setTimeout(() => {
        if (finalized || closed) return;
        reapedAfterResult = true;
        log(`   ${label}: terminal result frame received; reaping lingering child after ${grace}ms grace`);
        killTreeOnce();
        destroyStreams();
        finish(child.exitCode ?? 0);
      }, grace);
      if (typeof earlyTimer.unref === 'function') earlyTimer.unref();
    };

    const abortChild = () => chooseTerminal('aborted');
    const cleanup = () => {
      if (timer) clearTimeout(timer);
      if (idleTimer) clearTimeout(idleTimer);
      if (earlyTimer) clearTimeout(earlyTimer);
      if (closeGuardTimer) clearTimeout(closeGuardTimer);
      if (signal) signal.removeEventListener('abort', abortChild);
    };
    const finish = (code) => {
      if (finalized) return;
      finalized = true;
      closed = true;
      cleanup();
      destroyStreams();
      const effectiveCode = reapedAfterResult && (code == null || code !== 0) ? 0 : (code ?? null);
      const terminal = terminalCause
        || (spawnError ? 'spawn_error' : 'closed');
      resolve({
        code: effectiveCode,
        stdout,
        stderr,
        terminal,
        error: errorMessage(spawnError),
        kill_status: reapedAfterResult ? null : killStatus,
        ...(reapedAfterResult ? { reaped_after_result: true } : {}),
        spawned: true,
      });
    };

    child.stdout?.on('data', (chunk) => {
      if (!finalized) {
        stdout += chunk.toString();
        resetIdleTimer();
        checkEarlyCompletion();
      }
    });
    child.stderr?.on('data', (chunk) => {
      if (!finalized) {
        stderr += chunk.toString();
        resetIdleTimer();
      }
    });
    child.on('error', (error) => {
      if (finalized) return;
      spawnError = error;
      if (!child.pid) {
        finalized = true;
        cleanup();
        destroyStreams();
        resolve({
          code: null,
          stdout,
          stderr,
          terminal: 'spawn_error',
          error: errorMessage(error),
          kill_status: null,
          spawned: false,
        });
      }
    });
    child.on('close', (code) => finish(code));
    if (signal) signal.addEventListener('abort', abortChild, { once: true });
    if (signal?.aborted) abortChild();

    if (!terminalCause && Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => chooseTerminal('timeout'), timeoutMs);
      if (typeof timer.unref === 'function') timer.unref();
    }
    resetIdleTimer();

    if (!terminalCause && input != null && child.stdin) {
      child.stdin.on('error', (error) => {
        if (!terminalCause) log(`!! ${label}: child stdin failed: ${errorMessage(error)}`);
      });
      try { child.stdin.end(input); } catch (error) {
        log(`!! ${label}: child stdin failed: ${errorMessage(error)}`);
      }
    }
  });
}

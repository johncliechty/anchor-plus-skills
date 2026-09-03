import { spawn as nodeSpawn, spawnSync as nodeSpawnSync } from 'node:child_process';

function errorMessage(error) {
  return String(error?.message ?? error ?? '').slice(0, 500);
}

/**
 * Spawn one subscription CLI process and settle only after `close` (which follows
 * stdio drain). Abort/timeout choose the terminal cause and initiate one checked
 * process-tree kill; neither is an early-resolution path.
 */
export function runCloseBoundProcess({
  command,
  args = [],
  options = {},
  input = null,
  signal = null,
  timeoutMs = 0,
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
    let timer = null;

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
      terminalCause = cause;
      log(`!! ${label}: ${cause} - killing subscription child tree`);
      killTreeOnce();
    };

    const abortChild = () => chooseTerminal('aborted');
    const cleanup = () => {
      if (timer) clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', abortChild);
    };
    const finish = (code) => {
      if (finalized) return;
      finalized = true;
      closed = true;
      cleanup();
      const terminal = terminalCause
        || (spawnError ? 'spawn_error' : 'closed');
      resolve({
        code: code ?? null,
        stdout,
        stderr,
        terminal,
        error: errorMessage(spawnError),
        kill_status: killStatus,
        spawned: true,
      });
    };

    child.stdout?.on('data', (chunk) => {
      if (!finalized) stdout += chunk.toString();
    });
    child.stderr?.on('data', (chunk) => {
      if (!finalized) stderr += chunk.toString();
    });
    child.on('error', (error) => {
      if (finalized) return;
      spawnError = error;
      // A spawn error with no process is the sole path that need not wait for close.
      if (!child.pid) {
        finalized = true;
        cleanup();
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
    // Close the listener-install race.
    if (signal?.aborted) abortChild();

    if (!terminalCause && Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => chooseTerminal('timeout'), timeoutMs);
      if (typeof timer.unref === 'function') timer.unref();
    }

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

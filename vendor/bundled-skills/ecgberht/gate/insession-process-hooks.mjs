/**
 * Real OS-process hooks for the Wave-20 in-session executor.
 *
 * Lives under gate/ (NOT engine/) because engine law forbids importing
 * child_process or calling spawn* — durability tools and OS processes are
 * requested via injected hooks, never performed inside engine/.
 *
 * Used by: gate/t-host-0.mjs, gate/w20-real-run.mjs (pattern), and
 * engine/t-host-0.mjs via dynamic import when opts.hooks is not supplied.
 */

import fs from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';

/**
 * @param {number} pid
 * @returns {number} unix seconds
 */
export function procCreateTime(pid) {
  if (process.platform === 'win32') {
    const r = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        `(Get-Process -Id ${Number(pid)} -ErrorAction SilentlyContinue).StartTime.ToUniversalTime().Subtract([datetime]'1970-01-01').TotalSeconds`,
      ],
      { encoding: 'utf8', windowsHide: true },
    );
    const n = parseFloat(String(r.stdout || '').trim());
    return Number.isFinite(n) ? n : Date.now() / 1000;
  }
  try {
    const stat = fs.statSync(`/proc/${pid}`);
    return stat.birthtimeMs ? stat.birthtimeMs / 1000 : stat.ctimeMs / 1000;
  } catch {
    return Date.now() / 1000;
  }
}

/**
 * Real OS-process hooks for the Wave-20 in-session executor.
 * @returns {{ launch: Function, treeKill: Function, observeCreateTime: Function }}
 */
export function makeRealInSessionHooks() {
  return {
    launch: ({ cmdline: cmd, env, cwd }) => {
      const child = spawn(cmd[0], cmd.slice(1), {
        cwd,
        env,
        windowsHide: true,
        shell: false,
      });
      const pid = child.pid;
      const createTime = procCreateTime(pid);
      return {
        pid,
        proc_create_time: createTime,
        wait: () =>
          new Promise((resolve) => {
            child.on('exit', (code) => resolve({ code: code ?? 1 }));
            child.on('error', () => resolve({ code: 1 }));
          }),
        child,
      };
    },
    treeKill: ({ pid }) => {
      if (process.platform === 'win32') {
        spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
          windowsHide: true,
          stdio: 'ignore',
        });
      } else {
        try {
          process.kill(pid, 'SIGKILL');
        } catch {
          /* */
        }
      }
      return { ok: true };
    },
    observeCreateTime: (pid) => procCreateTime(pid),
  };
}

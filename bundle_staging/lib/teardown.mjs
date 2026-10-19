import { anchorSpawnSync } from './spawn.mjs';
import os from 'node:os';

/**
 * Cross-platform helper to kill a process tree.
 * Replaces hardcoded 'taskkill' calls.
 * 
 * @param {number} pid The process ID to kill.
 */
export function killTree(pid) {
    if (!pid) return;
    try {
        if (os.platform() === 'win32') {
            anchorSpawnSync('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true });
        } else {
            process.kill(-pid, 'SIGKILL');
        }
    } catch (e) {
        // Best-effort teardown, ignore errors
    }
}

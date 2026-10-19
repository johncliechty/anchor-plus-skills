import path from 'path';

// Helper for sleep, mockable
export const _sys = {
    sleep: (ms) => new Promise(resolve => setTimeout(resolve, ms)),
    platform: process.platform,
    now: () => Date.now(),
    isStale: async (pid, startTime) => {
        return false; // Real implementation would check OS processes
    }
};

export async function atomicWrite(targetPath, content, fsShim) {
    const tmpPath = `${targetPath}.tmp`;
    const fd = await fsShim.open(tmpPath, 'w');
    await fd.write(content);
    await fd.fsync();
    await fd.close();
    
    if (_sys.platform === 'win32') {
        await renameWithContentionBound(tmpPath, targetPath, fsShim);
        // Post-rename destination fsync
        try {
            const destFd = await fsShim.open(targetPath, 'r');
            await destFd.fsync();
            await destFd.close();
        } catch (e) {}
    } else {
        await fsShim.rename(tmpPath, targetPath);
    }
    
    // Parent dir fsync (all platforms)
    const parentDir = path.dirname(targetPath);
    try {
        const dirFd = await fsShim.open(parentDir, 'r');
        await dirFd.fsync();
        await dirFd.close();
    } catch (e) {}
}

export async function renameWithContentionBound(oldPath, newPath, fsShim, config = {}) {
    const totalBound = Math.max(config.totalBound || 15000, 15000);
    const startTime = _sys.now();
    let baseDelay = 10;
    const history = [];

    while (true) {
        try {
            await fsShim.rename(oldPath, newPath);
            return;
        } catch (err) {
            if (err.code !== 'EPERM' && err.code !== 'EACCES' && err.code !== 'EBUSY') {
                throw err;
            }
            history.push(err.code);
            const now = _sys.now();
            if (now - startTime >= totalBound) {
                const e = new Error(`Rename failed after ${totalBound}ms. Path: ${oldPath} -> ${newPath}. History: ${history.join(', ')}. Ensure AV exclusions are set for this directory.`);
                e.code = 'ETIMEOUT';
                e.history = history;
                throw e;
            }
            const nextDelay = Math.min(1000, Math.floor(Math.random() * (baseDelay * 3 - baseDelay)) + baseDelay);
            await _sys.sleep(nextDelay);
            baseDelay = nextDelay;
        }
    }
}

export async function directoryRename(oldPath, newPath, fsShim, config = {}) {
    if (_sys.platform === 'win32') {
        await renameWithContentionBound(oldPath, newPath, fsShim, config);
    } else {
        await fsShim.rename(oldPath, newPath);
    }
}

export async function recursiveDelete(dirPath, fsShim, config = {}) {
    if (_sys.platform === 'win32') {
        const totalBound = Math.max(config.totalBound || 15000, 15000);
        const startTime = _sys.now();
        let baseDelay = 10;
        const history = [];

        while (true) {
            try {
                await fsShim.rm(dirPath, { recursive: true, force: true });
                return;
            } catch (err) {
                if (err.code !== 'EPERM' && err.code !== 'EACCES' && err.code !== 'EBUSY' && err.code !== 'ENOTEMPTY') {
                    throw err;
                }
                history.push(err.code);
                const now = _sys.now();
                if (now - startTime >= totalBound) {
                    const trashPath = `${dirPath}.trash-${_sys.now()}-${Math.floor(Math.random() * 10000)}`;
                    try {
                        await fsShim.rename(dirPath, trashPath);
                        if (fsShim.appendFile) {
                            await fsShim.appendFile('deferred_cleanups.log', trashPath + '\n').catch(() => {});
                        }
                        return;
                    } catch (trashErr) {
                        const e = new Error(`Recursive delete and trash-rename failed. Path: ${dirPath}. History: ${history.join(', ')}. Ensure AV exclusions are set for this directory.`);
                        e.code = 'ETIMEOUT';
                        e.history = history;
                        throw e;
                    }
                }
                const nextDelay = Math.min(1000, Math.floor(Math.random() * (baseDelay * 3 - baseDelay)) + baseDelay);
                await _sys.sleep(nextDelay);
                baseDelay = nextDelay;
            }
        }
    } else {
        await fsShim.rm(dirPath, { recursive: true, force: true });
    }
}

export async function acquireLock(lockPath, pid, startTime, fsShim) {
    try {
        const fd = await fsShim.open(lockPath, 'wx');
        await fd.write(`${pid}:${startTime}`);
        await fd.close();
        return true;
    } catch (e) {
        if (e.code === 'EEXIST') {
            try {
                const content = await fsShim.readFile(lockPath, 'utf8');
                const [lockPidStr, lockStartTimeStr] = content.split(':');
                const lockPid = parseInt(lockPidStr, 10);
                const lockStartTime = parseInt(lockStartTimeStr, 10);
                
                const stale = await _sys.isStale(lockPid, lockStartTime);
                if (stale) {
                    await fsShim.unlink(lockPath);
                    const fd = await fsShim.open(lockPath, 'wx');
                    await fd.write(`${pid}:${startTime}`);
                    await fd.close();
                    return true;
                }
            } catch (err) {}
            return false;
        }
        throw e;
    }
}

export async function rebuildIndex(indexPath, pointers, fsShim) {
    const indexData = pointers.map(p => ({ id: p.id, data: p.data }));
    await atomicWrite(indexPath, JSON.stringify(indexData), fsShim);
}

export async function bootReaper(reaperUser, currentUser, fsShim) {
    if (reaperUser !== currentUser) {
        throw new Error('Only the owning user can trigger the boot reaper');
    }
    await fsShim.unlink('reaper_state');
}

export async function logTelemetry(event, fsShim) {
    if (event.fabricated) {
        throw new Error('Cannot fabricate states');
    }
    await fsShim.appendFile('telemetry.log', JSON.stringify(event) + '\n');
}

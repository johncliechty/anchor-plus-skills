import test from 'node:test';
import assert from 'node:assert';
import { FsShim } from './fs_shim.mjs';
import { 
    atomicWrite, 
    acquireLock, 
    directoryRename, 
    recursiveDelete, 
    _sys 
} from '../../lib/invariants.mjs';

// Mock _sys platform and sleep for testing
const originalPlatform = _sys.platform;
const originalSleep = _sys.sleep;
const originalNow = _sys.now;
const originalIsStale = _sys.isStale;

function setupWindowsMock(fsShim) {
    _sys.platform = 'win32';
    
    let currentTime = 100000;
    _sys.now = () => currentTime;
    
    const sleepLogs = [];
    _sys.sleep = async (ms) => {
        sleepLogs.push(ms);
        currentTime += ms;
    };
    
    return { 
        sleepLogs, 
        advanceTime: (ms) => { currentTime += ms; } 
    };
}

function teardownMock() {
    _sys.platform = originalPlatform;
    _sys.sleep = originalSleep;
    _sys.now = originalNow;
    _sys.isStale = originalIsStale;
}

test('Wave 4: Windows rename contention bound succeeds within 15s', async (t) => {
    const fsShim = new FsShim();
    const { sleepLogs } = setupWindowsMock(fsShim);
    
    const oldPath = 'file.txt.tmp';
    const newPath = 'file.txt';
    fsShim.files.set(oldPath, 'content');
    
    let attemptCount = 0;
    fsShim.mockError('rename', (o, n) => {
        if (attemptCount < 5) {
            attemptCount++;
            const err = new Error('EPERM');
            err.code = 'EPERM';
            return err;
        }
        return null;
    });
    
    await atomicWrite('file.txt', 'new content', fsShim);
    
    assert.strictEqual(attemptCount, 5, 'Should retry 5 times before succeeding');
    assert.strictEqual(sleepLogs.length, 5, 'Should sleep 5 times');
    // Ensure backoff happened
    assert.ok(sleepLogs[0] >= 10, 'First sleep should be >= 10ms');
    
    teardownMock();
});

test('Wave 4: Windows rename fails loudly exceeding total bound', async (t) => {
    const fsShim = new FsShim();
    setupWindowsMock(fsShim);
    
    fsShim.mockError('rename', () => {
        const err = new Error('EPERM');
        err.code = 'EPERM';
        return err;
    });
    
    let caughtError = null;
    try {
        await atomicWrite('file.txt', 'new content', fsShim);
    } catch (e) {
        caughtError = e;
    }
    
    assert.ok(caughtError, 'Should throw error');
    assert.strictEqual(caughtError.code, 'ETIMEOUT');
    assert.match(caughtError.message, /AV exclusions/);
    assert.match(caughtError.message, /Rename failed after/);
    assert.ok(caughtError.history.length > 5, 'Should have history of EPERMs');
    
    teardownMock();
});

test('Wave 4: Windows recursive delete escape hatch', async (t) => {
    const fsShim = new FsShim();
    setupWindowsMock(fsShim);
    
    fsShim.mockError('rm', () => {
        const err = new Error('EPERM');
        err.code = 'EPERM';
        return err;
    });
    
    await recursiveDelete('my_dir', fsShim);
    
    // Directory should have been renamed to .trash-...
    let trashPath = null;
    for (const key of fsShim.files.keys()) {
        if (key === 'deferred_cleanups.log') continue;
    }
    
    const logs = fsShim.files.get('deferred_cleanups.log');
    assert.ok(logs, 'Should record deferred cleanup');
    assert.match(logs, /my_dir\.trash-\d+-\d+/);
    
    teardownMock();
});

test('Wave 4: Lock takeover', async (t) => {
    const fsShim = new FsShim();
    _sys.isStale = async (pid, startTime) => {
        return pid === 1234; // mock dead process
    };
    
    await acquireLock('app.lock', 1234, 1000, fsShim);
    
    // Attempt to acquire with new PID
    const acquired = await acquireLock('app.lock', 5678, 2000, fsShim);
    assert.strictEqual(acquired, true, 'Should takeover lock');
    
    const content = fsShim.files.get('app.lock');
    assert.strictEqual(content, '5678:2000', 'Lock should contain new PID');
    
    teardownMock();
});

test('Wave 4: POSIX rename does not retry structurally', async (t) => {
    const fsShim = new FsShim();
    _sys.platform = 'linux';
    
    fsShim.mockError('rename', () => {
        const err = new Error('EPERM');
        err.code = 'EPERM';
        return err;
    });
    
    let caughtError = null;
    try {
        await atomicWrite('file.txt', 'new content', fsShim);
    } catch (e) {
        caughtError = e;
    }
    
    assert.ok(caughtError);
    assert.strictEqual(caughtError.code, 'EPERM'); // fails immediately
    
    teardownMock();
});

test('Wave 4: crash-between-steps never-torn', async (t) => {
    const fsShim = new FsShim();
    _sys.platform = 'linux';
    
    fsShim.files.set('target.txt', 'old content');
    
    // Mock a crash in fsync for the tmp file
    fsShim.mockError('fsync', (path) => {
        if (path === 'target.txt.tmp') {
            const err = new Error('CRASH');
            err.code = 'CRASH';
            return err;
        }
    });
    
    let caughtError = null;
    try {
        await atomicWrite('target.txt', 'new content', fsShim);
    } catch (e) {
        caughtError = e;
    }
    
    assert.ok(caughtError);
    assert.strictEqual(caughtError.code, 'CRASH');
    
    // The target file should remain untouched (never torn)
    const content = fsShim.files.get('target.txt');
    assert.strictEqual(content, 'old content');
    
    teardownMock();
});

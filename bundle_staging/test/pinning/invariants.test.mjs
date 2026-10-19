import test from 'node:test';
import assert from 'node:assert';
import path from 'path';
import { FsShim } from './fs_shim.mjs';
import { 
    atomicWrite, 
    acquireLock, 
    rebuildIndex, 
    bootReaper, 
    logTelemetry 
} from '../../lib/invariants.mjs';

test('1. CLI+secondary atomic writes', async (t) => {
    const fsShim = new FsShim();
    const target = '/data/file.txt';
    const parent = path.dirname(target);
    const content = 'test data';

    await atomicWrite(target, content, fsShim);

    const operations = fsShim.calls.map(c => c.method);
    
    // Assert 4-step sequence
    assert.ok(operations.includes('open'));
    assert.ok(operations.includes('write'));
    assert.ok(operations.includes('fsync'));
    assert.ok(operations.includes('rename'));

    // Specifically verify parent dir fsync
    const dirFsync = fsShim.calls.find(c => c.method === 'fsync' && c.args[0] === parent);
    assert.ok(dirFsync, 'Parent directory should be fsynced');
});

test('2. Cross-process lock', async (t) => {
    const fsShim = new FsShim();
    const lockPath = '/var/lock/app.lock';
    
    const acquired1 = await acquireLock(lockPath, 1234, Date.now(), fsShim);
    assert.strictEqual(acquired1, true, 'First lock should succeed');
    
    // Verify O_EXCL is used (wx)
    const lockOpenCall = fsShim.calls.find(c => c.method === 'open' && c.args[0] === lockPath);
    assert.strictEqual(lockOpenCall.args[1], 'wx', 'Lock must use wx (O_EXCL)');
    
    const acquired2 = await acquireLock(lockPath, 5678, Date.now(), fsShim);
    assert.strictEqual(acquired2, false, 'Second lock should fail due to EEXIST');
});

test('3. Torn-index rebuild-from-pointers', async (t) => {
    const fsShim = new FsShim();
    const pointers = [
        { id: '1', data: 'a' },
        { id: '2', data: 'b' }
    ];
    
    await rebuildIndex('/data/index.json', pointers, fsShim);
    
    const indexContent = await fsShim.readFile('/data/index.json', 'utf8');
    const parsed = JSON.parse(indexContent);
    assert.strictEqual(parsed.length, 2);
    assert.strictEqual(parsed[0].id, '1');
});

test('4. Boot-reaper owner-set', async (t) => {
    const fsShim = new FsShim();
    
    // Valid owner
    await assert.doesNotReject(async () => {
        await bootReaper('alice', 'alice', fsShim);
    });
    
    // Invalid owner
    await assert.rejects(
        async () => {
            await bootReaper('alice', 'bob', fsShim);
        },
        /Only the owning user can trigger the boot reaper/
    );
});

test('5. Telemetry/narration invariants', async (t) => {
    const fsShim = new FsShim();
    
    // Valid event
    await logTelemetry({ type: 'start', fabricated: false }, fsShim);
    
    // Fabricated event should be rejected
    await assert.rejects(
        async () => {
            await logTelemetry({ type: 'stop', fabricated: true }, fsShim);
        },
        /Cannot fabricate states/
    );
});

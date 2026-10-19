import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { ModuleCrawler } from '../../lib/entanglement.mjs';
import { SpendGate, LimitExceeded, scrubCredentials } from '../../lib/spend_gate.mjs';

test('Credential spend gate scrubs when closed', async () => {
    const env = {
        ANTHROPIC_API_KEY: 'sk-fake-123',
        CRUCIBLE_ALLOW_SPEND: '0',
        OTHER_VAR: 'val'
    };
    scrubCredentials(env);
    assert.strictEqual(env.ANTHROPIC_API_KEY, undefined);
    assert.strictEqual(env.OTHER_VAR, 'val');
    
    // Simulate paid endpoint network call attempt
    let fetchCalled = false;
    const origFetch = global.fetch;
    global.fetch = async (url) => {
        fetchCalled = true;
        if (url.includes('api.anthropic.com')) {
            throw new Error('Network call to paid endpoint');
        }
        return {};
    };
    try {
        if (env.ANTHROPIC_API_KEY) await global.fetch('https://api.anthropic.com/v1/messages');
    } catch (e) {}
    assert.strictEqual(fetchCalled, false, 'Should make zero network calls when key is scrubbed');
    global.fetch = origFetch;
    
    // Test allow spend
    const env2 = {
        ANTHROPIC_API_KEY: 'sk-fake-123',
        CRUCIBLE_ALLOW_SPEND: '1'
    };
    scrubCredentials(env2);
    assert.strictEqual(env2.ANTHROPIC_API_KEY, 'sk-fake-123');
});

test('SpendGate throws LimitExceeded on breach', () => {
    const gate = new SpendGate({ maxTokens: 100, maxDollars: 1.00 });
    
    // Should not throw
    gate.recordSpend(50, 0.50);
    assert.strictEqual(gate.spentTokens, 50);
    assert.strictEqual(gate.spentDollars, 0.50);
    
    // Should throw on tokens
    assert.throws(() => gate.recordSpend(60, 0), LimitExceeded);
    
    // Should throw on dollars
    assert.throws(() => gate.recordSpend(0, 2.00), LimitExceeded);
});

test('ModuleCrawler correctly parses and throws on cross-skill imports', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'crawler-test-'));
    try {
        // Create dummy skill folders
        const crucibleDir = path.join(tmpDir, 'crucible');
        const foremanDir = path.join(tmpDir, 'foreman');
        await fs.mkdir(crucibleDir, { recursive: true });
        await fs.mkdir(foremanDir, { recursive: true });
        
        // Good import
        await fs.writeFile(
            path.join(crucibleDir, 'good.mjs'), 
            `import { FsShim } from '../lib/fs-shim.mjs';\nconsole.log('hi');`
        );
        
        // Bad cross-skill import
        await fs.writeFile(
            path.join(crucibleDir, 'bad.mjs'), 
            `import { something } from '../foreman/index.mjs';\n`
        );
        
        const crawler = new ModuleCrawler();
        await assert.rejects(
            async () => {
                await crawler.assertBoundaryImmutability(tmpDir);
            },
            /Cross-skill import detected: crucible imports foreman/
        );
        
        // Clean bad file and assert pass
        await fs.rm(path.join(crucibleDir, 'bad.mjs'));
        await assert.doesNotReject(async () => {
            await crawler.assertBoundaryImmutability(tmpDir);
        });

    } finally {
        await fs.rm(tmpDir, { recursive: true, force: true });
    }
});

test('ModuleCrawler correctly throws on portability issues', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'portability-test-'));
    try {
        const crawler = new ModuleCrawler();
        
        // Hardcoded path separator
        await fs.writeFile(path.join(tmpDir, 'hardcoded.mjs'), `const x = 'C:\\\\path';`);
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Hardcoded path separator detected/
        );
        await fs.rm(path.join(tmpDir, 'hardcoded.mjs'));

        // Case-mismatched import
        await fs.writeFile(path.join(tmpDir, 'CamelCase.mjs'), `console.log('hi');`);
        await fs.writeFile(path.join(tmpDir, 'consumer.mjs'), `import { thing } from './camelcase.mjs';`);
        
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Case-mismatched import detected/
        );
    } finally {
        await fs.rm(tmpDir, { recursive: true, force: true });
    }
});

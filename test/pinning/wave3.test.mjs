import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { ModuleCrawler } from '../../lib/entanglement.mjs';

test('ModuleCrawler correctly throws on literal cross-sibling paths', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'wave3-test-'));
    try {
        const crawler = new ModuleCrawler();
        
        // Good path
        await fs.writeFile(path.join(tmpDir, 'good.mjs'), `const x = 'relative/path';`);
        await assert.doesNotReject(async () => crawler.assertPortability(tmpDir));
        await fs.rm(path.join(tmpDir, 'good.mjs'));

        // Bad path 1
        await fs.writeFile(path.join(tmpDir, 'bad1.mjs'), `const p = 'C:\\\\dev\\\\Anchor';`);
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Literal cross-sibling path detected/
        );
        await fs.rm(path.join(tmpDir, 'bad1.mjs'));

        // Bad path 2
        await fs.writeFile(path.join(tmpDir, 'bad2.mjs'), `const p = '/dev/trio/';`);
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Literal cross-sibling path detected/
        );
        
    } finally {
        await fs.rm(tmpDir, { recursive: true, force: true });
    }
});

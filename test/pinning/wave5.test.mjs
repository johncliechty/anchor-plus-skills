import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { ModuleCrawler } from '../../lib/entanglement.mjs';
import { anchorSpawnSync } from '../../lib/spawn.mjs';

test('Wave 5 - Journal records argv and constructed env, no wholesale inheritance', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'spawn-test-'));
    const journalPath = path.join(tmpDir, 'spawn-journal.jsonl');
    
    try {
        const originalEnv = process.env.NODE_ENV;
        process.env.NODE_ENV = 'test';
        process.env.SPAWN_JOURNAL_PATH = journalPath;
        process.env.TEST_UNALLOWED_VAR = 'should-not-inherit';
        process.env.PORT = '8780'; // an allowed var

        // Execute a trivial spawn
        anchorSpawnSync('node', ['-v'], { env: { CUSTOM_OVERRIDE: 'yes' } });
        
        process.env.NODE_ENV = originalEnv;

        const journalText = await fs.readFile(journalPath, 'utf8');
        const lines = journalText.trim().split('\n');
        assert.strictEqual(lines.length, 1);
        
        const entry = JSON.parse(lines[0]);
        assert.strictEqual(entry.cmd, 'node');
        assert.deepStrictEqual(entry.args, ['-v']);
        assert.strictEqual(entry.env.PORT, '8780');
        assert.strictEqual(entry.env.TEST_UNALLOWED_VAR, undefined, 'Should not inherit unallowed vars wholesale');
        assert.strictEqual(entry.env.CUSTOM_OVERRIDE, 'yes', 'Should accept explicit option overrides');

    } finally {
        await fs.rm(tmpDir, { recursive: true, force: true });
    }
});

test('Wave 5 - Lint fails on unsanctioned child_process spawn', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'spawn-lint-'));
    try {
        const crawler = new ModuleCrawler();
        
        // Unsanctioned spawn
        await fs.writeFile(path.join(tmpDir, 'bad-spawn.mjs'), `import { spawn } from 'node:child_process';`);
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Unsanctioned spawn detected.*all spawn calls must use lib[\\\/]spawn.mjs/
        );

        // Another unsanctioned pattern
        await fs.writeFile(path.join(tmpDir, 'bad-spawn2.mjs'), `const cp = require("child_process");`);
        await assert.rejects(
            async () => crawler.assertPortability(tmpDir),
            /Unsanctioned spawn detected.*all spawn calls must use lib[\\\/]spawn.mjs/
        );
        
    } finally {
        await fs.rm(tmpDir, { recursive: true, force: true });
    }
});

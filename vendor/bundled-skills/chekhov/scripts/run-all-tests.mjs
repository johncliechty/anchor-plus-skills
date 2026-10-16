/**
 * Windows-safe expanding gate: list test/*.test.mjs explicitly.
 * Bare `node --test test/` is hard-broken on Windows Node (Foreman isBadNodeTestDirectoryCommand).
 * Usage (plan test-command): node scripts/run-all-tests.mjs
 * Sleep 0076 package 4 / Crucible Stage-2 default emit.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const testDir = path.join(root, 'test');
let files = [];
try {
  files = fs
    .readdirSync(testDir)
    .filter((f) => f.endsWith('.test.mjs') || f.endsWith('.test.js'))
    .sort()
    .map((f) => path.join('test', f));
} catch {
  console.error('run-all-tests: test/ directory missing or unreadable');
  process.exit(2);
}

if (!files.length) {
  console.error('run-all-tests: no test/*.test.mjs files found');
  process.exit(2);
}

// Serial file execution: the w01 tests initialise the REAL writing roots
// (git init, zip extraction) — two test processes racing on the same root
// would corrupt the extraction. One file at a time, sorted order.
const r = spawnSync(process.execPath, ['--test', '--test-concurrency=1', ...files], {
  cwd: root,
  stdio: 'inherit',
  windowsHide: true,
  shell: false,
});
process.exit(typeof r.status === 'number' ? r.status : 1);

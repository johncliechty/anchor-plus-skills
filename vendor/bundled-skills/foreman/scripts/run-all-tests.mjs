#!/usr/bin/env node
// run-all-tests.mjs — Canonical Foreman test runner.
// Runs only top-level `test/*.test.mjs` files (excluding `fixtures/**` and
// `test/fixture/**` which hold intentionally-red canonical fixture suites),
// and strips `NODE_TEST_CONTEXT` from the child env so `node --test` never
// treats top-level runs as nested subtests.

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, '..');
const testDir = path.join(rootDir, 'test');

const filterArgs = process.argv.slice(2);
let files = fs.readdirSync(testDir, { withFileTypes: true })
  .filter((ent) => ent.isFile() && ent.name.endsWith('.test.mjs'))
  .map((ent) => path.join('test', ent.name))
  .sort();

if (filterArgs.length > 0) {
  files = files.filter((rel) => filterArgs.some((f) => rel.includes(f)));
}

if (files.length === 0) {
  console.error('[foreman:test] no matching test/*.test.mjs files found');
  process.exit(1);
}

const env = { ...process.env };
delete env.NODE_TEST_CONTEXT;

const res = spawnSync(process.execPath, ['--test', ...files], {
  cwd: rootDir,
  env,
  stdio: 'inherit',
  windowsHide: true,
  shell: false,
});

process.exit(res.status ?? 1);

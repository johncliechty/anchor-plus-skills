#!/usr/bin/env node
// scripts/run-all-tests.mjs — Cross-platform deterministic test runner for researchPrime.
// Enumerates test/*.test.mjs explicitly and spawns `node --test` with shell:false and windowsHide:true.

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_DIR = path.join(ROOT, 'test');

const files = fs
  .readdirSync(TEST_DIR)
  .filter((f) => f.endsWith('.test.mjs') || f.endsWith('.test.js'))
  .sort()
  .map((f) => path.join(TEST_DIR, f));

if (!files.length) {
  process.stderr.write('No test files found under test/\n');
  process.exit(1);
}

const env = { ...process.env };
delete env.NODE_TEST_CONTEXT;

const res = spawnSync(process.execPath, ['--test', ...files], {
  cwd: ROOT,
  env,
  stdio: 'inherit',
  windowsHide: true,
  shell: false,
});

process.exit(res.status ?? 1);

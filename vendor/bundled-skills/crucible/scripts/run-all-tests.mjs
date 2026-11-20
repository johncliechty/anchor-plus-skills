#!/usr/bin/env node
// scripts/run-all-tests.mjs — Windows-safe expanding test runner for Crucible.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_DIR = path.join(ROOT, 'test');

function collectTests(dir) {
  if (!fs.existsSync(dir)) return [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name.startsWith('_') || e.name === 'node_modules') continue;
      files.push(...collectTests(full));
    } else if (e.isFile() && e.name.endsWith('.test.mjs')) {
      files.push(full);
    }
  }
  return files.sort();
}

const files = collectTests(TEST_DIR);
if (!files.length) {
  process.stderr.write('run-all-tests: no *.test.mjs files found under test/\n');
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

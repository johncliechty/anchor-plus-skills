#!/usr/bin/env node
// Anchor sleep cycle — money-safe default gate: only tests matching 2026_07_29
// (per-wave gate-command: lines in IMPLEMENTATION-PLAN.md are authoritative when Foreman scopes them)
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const r = spawnSync(
  process.platform === 'win32' ? 'python' : 'python3',
  ['-m', 'pytest', '-v', 'tests/', '-k', '2026_07_29', '--tb=line'],
  { cwd: repoRoot, stdio: 'inherit', shell: false, env: process.env },
);
process.exit(r.status == null ? 1 : r.status);

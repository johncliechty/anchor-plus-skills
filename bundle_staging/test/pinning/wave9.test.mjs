import test from 'node:test';
import assert from 'node:assert';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs/promises';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../../');
const STAGED_BUNDLE = path.resolve(REPO_ROOT, 'bundle_staging');

test('Wave 9 - Bundle Build', () => {
    const res = spawnSync('node', ['tools/build_bundle.mjs'], { cwd: REPO_ROOT });
    assert.strictEqual(res.status, 0, `Build failed: ${res.stderr.toString()}`);
});

test('Wave 9 - Leak Scan', () => {
    const res = spawnSync('node', ['tools/leak_scan.mjs'], { cwd: REPO_ROOT });
    assert.strictEqual(res.status, 0, `Leak scan failed: ${res.stderr.toString()}`);
});

test('Wave 9 - Pure-JS Lockfile Lint', () => {
    const res = spawnSync('node', ['tools/lint_lockfile.mjs'], { cwd: REPO_ROOT });
    assert.strictEqual(res.status, 0, `Lockfile lint failed: ${res.stderr.toString()}`);
});

test('Wave 9 - Doc Consistency Checker', () => {
    const res = spawnSync('node', ['tools/doc_consistency.mjs'], { cwd: REPO_ROOT });
    assert.strictEqual(res.status, 0, `Doc consistency check failed: ${res.stderr.toString()}`);
});

test('Wave 9 - npm ci --ignore-scripts', async () => {
    const hasPackage = await fs.access(path.join(STAGED_BUNDLE, 'package.json')).then(() => true).catch(() => false);
    if (hasPackage) {
        const res = spawnSync('npm', ['ci', '--ignore-scripts'], { cwd: STAGED_BUNDLE, shell: true });
        assert.strictEqual(res.status, 0, `npm ci failed: ${res.stderr?.toString()}`);
    }
});

test('Wave 9 - Boot Smoke & Integration Smoke', async () => {
    const foreignRoot = path.join(os.tmpdir(), `anchor-bundle-${Date.now()}`);
    await fs.mkdir(foreignRoot, { recursive: true });
    
    // Copy bundle to foreign root
    const bundleDir = path.join(foreignRoot, 'bundle_staging');
    await fs.cp(STAGED_BUNDLE, bundleDir, { recursive: true });
    
    // Boot smoke: import anchor_gui
    const py = spawnSync('python', ['-c', 'import sys; sys.path.insert(0, "."); import anchor_gui'], { cwd: bundleDir });
    assert.strictEqual(py.status, 0, `Boot smoke failed: ${py.stderr?.toString()}`);

    const smokeRes = spawnSync('node', ['tools/smoke_integration.mjs'], { cwd: bundleDir, shell: true });
    assert.strictEqual(smokeRes.status, 0, `Integration smoke failed: ${smokeRes.stderr?.toString()}`);
});

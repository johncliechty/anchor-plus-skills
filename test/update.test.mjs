import { execSync } from 'child_process';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ANCHOR_PY_PATH = join(__dirname, '..', 'anchor.py');

function run(cmd, cwd) {
    console.log(`> ${cmd}`);
    return execSync(cmd, { cwd, encoding: 'utf-8' });
}

function runCatch(cmd, cwd, env={}) {
    console.log(`> ${cmd} (catch)`);
    try {
        const out = execSync(cmd, { cwd, encoding: 'utf-8', env: { ...process.env, ...env } });
        return { success: true, output: out };
    } catch (e) {
        return { success: false, output: e.stdout + '\\n' + e.stderr, error: e };
    }
}

function createTestFixture() {
    const root = mkdtempSync(join(tmpdir(), 'anchor-update-test-'));
    const originDir = join(root, 'origin');
    const localDir = join(root, 'local');
    
    // 1. Create origin repo
    run('git init origin', root);
    // configure git name/email to avoid warnings
    run('git config user.name "Test"', originDir);
    run('git config user.email "test@example.com"', originDir);
    // write pinned signers config
    writeFileSync(join(originDir, 'allowed_signers'), 'mock_signer_key\\n');
    
    // Create base v1 commit
    writeFileSync(join(originDir, 'file.txt'), 'v1\\n');
    run('git add .', originDir);
    run('git commit -m "v1"', originDir);
    run('git tag -a v1 -m "Release v1"', originDir); // ssh signing mocked for now
    
    // Create v2 commit
    writeFileSync(join(originDir, 'file.txt'), 'v2\\n');
    writeFileSync(join(originDir, 'new_dep.js'), 'console.log("dep");\\n');
    run('git add .', originDir);
    run('git commit -m "v2"', originDir);
    run('git tag -a v2 -m "Release v2"', originDir);
    
    // 2. Create local clone of v1
    run('git clone origin local', root);
    run('git config user.name "Test"', localDir);
    run('git config user.email "test@example.com"', localDir);
    run('git checkout v1', localDir);
    
    // 3. Make diverged commit in local
    writeFileSync(join(localDir, 'local_file.txt'), 'local commit\\n');
    run('git add local_file.txt', localDir);
    run('git commit -m "local diverged commit"', localDir);
    
    // 4. Make uncommitted edits in local
    writeFileSync(join(localDir, 'file.txt'), 'v1 edited\\n'); // modified shipped file
    writeFileSync(join(localDir, 'untracked.txt'), 'untracked\\n');
    
    return { root, localDir, originDir };
}

function testNormalUpdate() {
    console.log("\\n--- Testing Normal Update ---");
    const fixture = createTestFixture();
    try {
        process.env.ANCHOR_DATA_DIR = fixture.localDir;
        process.env.ANCHOR_UPDATE_TARGET = fixture.localDir;
        
        const pyCmd = `python "${ANCHOR_PY_PATH}" update`;
        console.log(run(pyCmd, fixture.localDir));
        
        const log = run('git log --oneline -n 3', fixture.localDir);
        if (!log.includes('v2')) throw new Error("Expected to be on v2 after update");
        console.log("Test Normal Update passed!");
    } finally {
        rmSync(fixture.root, { recursive: true, force: true });
    }
}

function testRollback() {
    console.log("\\n--- Testing Rollback ---");
    const fixture = createTestFixture();
    try {
        process.env.ANCHOR_DATA_DIR = fixture.localDir;
        process.env.ANCHOR_UPDATE_TARGET = fixture.localDir;
        
        const pyCmd = `python "${ANCHOR_PY_PATH}" update`;
        
        // Inject step-6 failure
        const res = runCatch(pyCmd, fixture.localDir, { INJECT_STEP6_FAILURE: '1' });
        console.log("Update output:", res.output);
        if (res.success) throw new Error("Expected update to fail at step 6");
        
        if (res.output.includes('git ') || res.output.includes('openssl ')) {
            throw new Error("Found 'git ' or 'openssl ' in error output. Mechanical assertion failed.");
        }
        
        // Check if rolled back to diverged commit
        const log = run('git log --oneline -n 3', fixture.localDir);
        if (log.includes('v2')) throw new Error("Rollback failed: still on v2 commit");
        if (!log.includes('local diverged commit')) throw new Error("Rollback failed: lost local diverged commit");
        
        console.log("Test Rollback passed!");
    } finally {
        rmSync(fixture.root, { recursive: true, force: true });
    }
}

function testInterruptedResume() {
    console.log("\n--- Testing Interrupted Resume ---");
    const fixture = createTestFixture();
    try {
        process.env.ANCHOR_DATA_DIR = fixture.localDir;
        process.env.ANCHOR_UPDATE_TARGET = fixture.localDir;
        
        const pyCmd = `python "${ANCHOR_PY_PATH}" update`;
        
        // Inject step-4 failure
        const res = runCatch(pyCmd, fixture.localDir, { INJECT_STEP4_FAILURE: '1' });
        console.log("Update output:", res.output);
        if (res.success) throw new Error("Expected update to fail at step 4");
        
        // Resume
        const pyCmdResume = `python "${ANCHOR_PY_PATH}" update --resume`;
        console.log(run(pyCmdResume, fixture.localDir));
        
        const log = run('git log --oneline -n 3', fixture.localDir);
        if (!log.includes('v2')) throw new Error("Expected to be on v2 after resumed update");
        console.log("Test Interrupted Resume passed!");
    } finally {
        rmSync(fixture.root, { recursive: true, force: true });
    }
}

testNormalUpdate();
testRollback();
testInterruptedResume();

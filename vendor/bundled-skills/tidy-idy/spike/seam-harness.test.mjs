// spike/seam-harness.test.mjs — Wave 0 seam spike: MEASURE, don't assume.
//
// Standalone harness that (1) imports each tidy-idy stage module individually and
// records import-time success/throw and git-or-Foundry assumptions, (2) runs
// scanner+hygiene (and corroborating probes of the other stages) against a
// generated plain temp folder — no .git, no North-Star, no SKILL.md — capturing
// every failure, hard-coded path, and outside-target-root write as a
// coupling-inventory record instead of crashing, and (3) cross-checks the
// checked-in spike/coupling-inventory.json and spike/gate-verdict.json against
// the measured seam set, so the inventory and the N=5 gate verdict can never
// drift from reality while the suite is green. A seam FIRING is a green test
// with the seam captured; only measurement-vs-inventory drift is red.
//
// It also re-runs the seven legacy test files in a subprocess so every gate run
// records the green baseline the later waves must preserve (spike/baseline-record.md).
//
// WAVE-1 UPDATE (refactor-in-place). The gate verdict formally scoped Wave 1's
// first deliverable as the refactor-in-place of the recorded seams, and every
// inventory record carries the `proposed-fix` that Wave 1 was to apply. So the
// harness now measures each seam's STATUS — 'open' (still present, as first
// measured) or 'resolved' (Wave 1 applied the recorded fix and the seam is
// measurably GONE) — and the cross-check requires the checked-in inventory to
// agree with the measurement on module, kind AND status.
//
// This makes the harness STRONGER, not weaker: a resolved seam's test now fails
// if the seam ever comes BACK (a regression guard the original assertions could
// not provide), and an open seam's test still fails if it silently disappears
// without the inventory being updated. Drift in either direction is red.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillRoot = path.resolve(__dirname, '..');
const binDir = path.join(skillRoot, 'bin');

const STAGE_MODULES = ['scanner.mjs', 'hygiene.mjs', 'analyze.mjs', 'debate.mjs', 'remove.mjs', 'compress.mjs'];
const DRIVER_PATH_LITERAL = 'fil<path>';
const CWD_STATE_LITERAL = "path.resolve('.tidy-idy'";
const CLI_STATE_MODULES = ['scanner.mjs', 'hygiene.mjs', 'analyze.mjs', 'debate.mjs', 'compress.mjs'];
const LEGACY_SUITE = ['analyze', 'compress', 'debate', 'hygiene', 'remove', 'scanner', 'tidy']
  .map((n) => path.join('test', `${n}.test.mjs`));
const KINDS = ['hardcoded-path', 'import-time-git', 'shared-mutable-state', 'foundry-marker-assumption'];
// Wave-1 addition: every inventory record now carries a measured lifecycle
// status. 'open' = the seam is still present (as first measured); 'resolved' =
// Wave 1 applied the record's proposed-fix and the seam is measurably gone.
const STATUSES = ['open', 'resolved'];

// Writable sink standing in for process.stdout so library prompts/refusals are
// captured, never printed, and process.exit paths are never reached.
class Sink {
  constructor() { this.buf = ''; }
  write(s) { this.buf += String(s); return true; }
}

// The measured record: what the harness actually observed this run. The
// cross-check test asserts the checked-in inventory matches this exactly.
const measured = {
  imports: {},           // module -> { ok, error }
  seams: [],             // { module, kind, evidence }
  probes: {},            // free-form probe results for the debug dump
};
function recordSeam(module, kind, evidence, status = 'open') {
  measured.seams.push({ module: `bin/${module}`, kind, status, evidence });
}

async function snapshotTree(root) {
  const entries = [];
  async function walk(dir) {
    const items = await fs.readdir(dir, { withFileTypes: true });
    for (const it of items) {
      const p = path.join(dir, it.name);
      if (it.isDirectory()) {
        entries.push({ p: path.relative(root, p), dir: true });
        await walk(p);
      } else {
        const st = await fs.stat(p);
        entries.push({ p: path.relative(root, p), size: st.size, mtime: st.mtimeMs });
      }
    }
  }
  await walk(root);
  return entries.sort((a, b) => a.p.localeCompare(b.p));
}

let tmpRoot;      // parent for every generated folder; removed in after()
let plainDir;     // the plain folder: no .git, no North-Star, no SKILL.md
let compressDir;  // plain folder with an agent.md for the compress probe
let removalDir;   // plain folder with a junk file for the remove probe
let cliCwdDir;    // CWD for the scanner-CLI spawn probe
let cliTargetDir; // target for the scanner-CLI spawn probe
const mods = {};  // dynamically imported stage modules

let priorGitCeiling;  // saved so after() restores the host env exactly

before(async () => {
  tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-spike-'));
  // Hermeticity (Wave-0 hardening). A host can accumulate stray `.git` dirs in the
  // ancestry of os.tmpdir() (an accidental `git init` at a Temp/AppData level), which
  // makes EVERY generated folder read as "inside a git work tree" and invalidates the
  // non-git probes below (the exact failure this guard prevents). Ceil git repository
  // discovery at our own spike temp root so no ancestor repo can ever be discovered —
  // the probes then measure the tidy-idy modules, never the host's git pollution.
  priorGitCeiling = process.env.GIT_CEILING_DIRECTORIES;
  process.env.GIT_CEILING_DIRECTORIES = tmpRoot;
  plainDir = path.join(tmpRoot, 'plain');
  compressDir = path.join(tmpRoot, 'plain-compress');
  removalDir = path.join(tmpRoot, 'plain-removal');
  cliCwdDir = path.join(tmpRoot, 'cli-cwd');
  cliTargetDir = path.join(tmpRoot, 'cli-target');
  for (const d of [plainDir, compressDir, removalDir, cliCwdDir, cliTargetDir]) {
    await fs.mkdir(d, { recursive: true });
  }
  await fs.writeFile(path.join(plainDir, 'old.log'), 'stale log line\n');
  await fs.writeFile(path.join(plainDir, 'notes.txt'), 'ordinary user notes\n');
  await fs.writeFile(path.join(compressDir, 'agent.md'), '# agent\n\nActive goal: X\n\n## Old log\n2019: did things\n');
  await fs.writeFile(path.join(removalDir, 'junk.txt'), 'junk to remove\n');
  await fs.writeFile(path.join(cliTargetDir, 'file.txt'), 'plain file\n');

  // Import every stage module here (not inside individual tests) so the runtime
  // probes never depend on test ordering; the import tests assert these records.
  for (const m of STAGE_MODULES) {
    try {
      mods[m] = await import(pathToFileURL(path.join(binDir, m)).href);
      measured.imports[m] = { ok: true };
    } catch (err) {
      measured.imports[m] = { ok: false, error: String(err && err.message) };
    }
  }
});

after(async () => {
  // Restore the host env exactly (no leak into sibling test files/processes).
  if (priorGitCeiling === undefined) delete process.env.GIT_CEILING_DIRECTORIES;
  else process.env.GIT_CEILING_DIRECTORIES = priorGitCeiling;
  if (tmpRoot) await fs.rm(tmpRoot, { recursive: true, force: true, maxRetries: 5 });
});

describe('Wave-0 seam spike — import-time measurement', () => {
  for (const m of STAGE_MODULES) {
    test(`${m} imports cleanly outside a Foundry git repo (no import-time git/Foundry assumption)`, () => {
      // The measured truth (recorded in the inventory's import_time_summary):
      // every stage module imports cleanly; all seams fire at RUNTIME. If a
      // future edit breaks import, this goes red and the inventory must gain
      // a real import-time record.
      assert.ok(measured.imports[m] && measured.imports[m].ok,
        `${m} threw at import time — a NEW import-time seam the coupling inventory does not record: ${measured.imports[m] && measured.imports[m].error}`);
    });
  }
});

describe('Wave-0 seam spike — static hard-coded-path / ordering scans', () => {
  test('RESOLVED (Wave 1): analyze/debate/compress no longer bake in the absolute driver path (hardcoded-path ×3)', async () => {
    for (const m of ['analyze.mjs', 'debate.mjs', 'compress.mjs']) {
      const src = await fs.readFile(path.join(binDir, m), 'utf8');
      // Regression guard: the seam is CLOSED and must stay closed.
      assert.ok(!src.includes(DRIVER_PATH_LITERAL),
        `${m} has REGRESSED: the hardcoded driver path '${DRIVER_PATH_LITERAL}' is back. The Wave-1 fix (engine/agent-seam.mjs resolveAgent) must remain the only driver resolution.`);
      assert.ok(/resolveAgent\(/.test(src),
        `${m} no longer resolves its LLM seam through resolveAgent() — the recorded Wave-1 fix is gone; update spike/coupling-inventory.json to match reality`);
      recordSeam(m, 'hardcoded-path',
        'resolved: driver resolved via engine/agent-seam.mjs resolveAgent() (injected agent → config driverPath → env var), loud failure when unresolvable; the absolute machine path is absent from the source',
        'resolved');
    }
  });

  test('RESOLVED (Wave 1): no CLI main() transports state through a CWD-relative .tidy-idy/ (shared-mutable-state ×5)', async () => {
    for (const m of CLI_STATE_MODULES) {
      const src = await fs.readFile(path.join(binDir, m), 'utf8');
      assert.ok(!src.includes(CWD_STATE_LITERAL),
        `${m} has REGRESSED: ${CWD_STATE_LITERAL}) is back — state must be derived from the TARGET ROOT via engine/report-dir.mjs reportDirFor(), never from the CWD`);
      assert.ok(/reportDirFor\(/.test(src),
        `${m} no longer derives its state location through reportDirFor() — the recorded Wave-1 fix is gone; update spike/coupling-inventory.json to match reality`);
      recordSeam(m, 'shared-mutable-state',
        'resolved: state/report location derived from the target root via engine/report-dir.mjs reportDirFor(); no CWD-relative state path remains in the source',
        'resolved');
    }
  });

  test('remove.mjs deletes files BEFORE the git commit that archives them (import-time-git: delete-then-commit ordering)', async () => {
    const src = await fs.readFile(path.join(binDir, 'remove.mjs'), 'utf8');
    const rmIdx = src.indexOf('await fs.rm(');
    const commitIdx = src.indexOf('git add -A');
    assert.ok(rmIdx !== -1 && commitIdx !== -1 && rmIdx < commitIdx,
      'remove.mjs ordering changed (fs.rm vs git add -A) — update spike/coupling-inventory.json to match reality');
    recordSeam('remove.mjs', 'import-time-git', 'fs.rm precedes the archiving git commit; commit failure throws AFTER deletion');
  });
});

describe('Wave-0 seam spike — plain-temp-folder runtime probes (no .git, no North-Star, no SKILL.md)', () => {
  test('scanner: scan() returns [] on the plain folder (foundry-marker-assumption) and performs zero writes', async () => {
    const beforeSnap = await snapshotTree(plainDir);
    const cwdStateDir = path.join(process.cwd(), '.tidy-idy');
    const cwdStatePreExisting = existsSync(cwdStateDir);

    const projects = await mods['scanner.mjs'].scan(plainDir);

    assert.deepStrictEqual(projects, [],
      'scan() now finds projects in a marker-less plain folder — the foundry-marker-assumption seam is GONE; update the inventory');
    assert.deepStrictEqual(await snapshotTree(plainDir), beforeSnap, 'scan() wrote inside the plain folder');
    assert.strictEqual(existsSync(cwdStateDir), cwdStatePreExisting, 'scan() created .tidy-idy state in the CWD');
    recordSeam('scanner.mjs', 'foundry-marker-assumption', 'scan(<plain folder>) === [] — folder invisible without NORTH-STAR/INTENT/SKILL.md');
    measured.probes.scanner = { projects: 0, wroteNothing: true };
  });

  test('hygiene: non-git folder is hard-refused via throw (runtime git assumption), no process.exit, no writes', async () => {
    const sink = new Sink();
    const status = await mods['hygiene.mjs'].checkProjectHygiene(plainDir);
    assert.strictEqual(status.isGit, false,
      `precondition violated: the generated temp folder reads as a git work tree (${plainDir}) — the environment invalidates this probe`);

    const beforeSnap = await snapshotTree(plainDir);
    await assert.rejects(
      mods['hygiene.mjs'].runHygieneCheck(plainDir, { stdout: sink, interactive: false, throwOnError: true }),
      /is not a git repository/,
      'runHygieneCheck no longer hard-refuses non-git folders — the git-assumption seam changed; update the inventory');
    assert.match(sink.buf, /REFUSED/, 'the refusal is expected to be LOUD on the provided stream');
    assert.deepStrictEqual(await snapshotTree(plainDir), beforeSnap, 'runHygieneCheck wrote inside the plain folder');
    recordSeam('hygiene.mjs', 'import-time-git', 'runHygieneCheck(<plain folder>) throws the non-git refusal (runtime, not import-time)');
    measured.probes.hygiene = { isGit: false, refusalThrown: true };
  });

  test('analyze: runAnalysis() throws "No North Star file found" on the plain folder (foundry-marker-assumption)', async () => {
    await assert.rejects(
      mods['analyze.mjs'].runAnalysis(plainDir, { throwOnError: true, agent: async () => [] }),
      /No North Star file found/,
      'runAnalysis no longer requires a North-Star marker — the seam changed; update the inventory');
    recordSeam('analyze.mjs', 'foundry-marker-assumption', 'runAnalysis(<plain folder>) throws No North Star file found');
  });

  test('debate: runDebate() throws "No North Star file found" on the plain folder even with suspects supplied (foundry-marker-assumption)', async () => {
    await assert.rejects(
      mods['debate.mjs'].runDebate(plainDir, [{ filepath: path.join(plainDir, 'old.log'), reason: 'junk' }], { agent: async () => [] }),
      /No North Star file found/,
      'runDebate no longer requires a North-Star marker — the seam changed; update the inventory');
    recordSeam('debate.mjs', 'foundry-marker-assumption', 'runDebate(<plain folder>, suspects) throws No North Star file found');
  });

  test('compress: runCompression() completes on the plain non-git folder with an injected agent (no marker/git seam — driver default is its only coupling)', async () => {
    const res = await mods['compress.mjs'].runCompression(compressDir, {
      agent: async () => ({ executiveSummary: '# agent\n\nActive goal: X', historyToAppend: '' }),
    });
    assert.strictEqual(res.agentCompressed, true, 'compress failed on a plain folder — a NEW runtime seam the inventory does not record');
    assert.strictEqual(await fs.readFile(path.join(compressDir, 'agent.md'), 'utf8'), '# agent\n\nActive goal: X');
    measured.probes.compress = { ranOnPlainFolder: true };
  });

  test('remove (corroboration): on a non-git folder the file is DELETED first, then the archiving commit hard-fails — no archive exists', async (t) => {
    // Guard: only meaningful when the temp dir is genuinely outside any work tree.
    let insideRepo = false;
    try {
      const { stdout } = await execFileAsync('git', ['rev-parse', '--is-inside-work-tree'], { cwd: removalDir });
      insideRepo = stdout.trim() === 'true';
    } catch { insideRepo = false; }
    if (insideRepo) {
      t.skip('temp dir unexpectedly sits inside a git work tree — dynamic probe skipped (the static ordering evidence stands)');
      return;
    }
    const junkPath = path.join(removalDir, 'junk.txt');
    await assert.rejects(
      mods['remove.mjs'].runRemoval(removalDir, [{ filepath: 'junk.txt', decision: 'REMOVE', reasoning: 'junk' }],
        { interactive: false, stdout: new Sink() }),
      /removal commit FAILED/,
      'runRemoval no longer hard-fails after deletion on non-git — the seam changed; update the inventory');
    assert.strictEqual(existsSync(junkPath), false,
      'expected the load-bearing capture: the file is already deleted when the commit fails');
    measured.probes.remove = { deletedBeforeCommitFailure: true };
  });

  test('RESOLVED (Wave 1) scanner CLI: `node bin/scanner.mjs <target>` writes state UNDER THE TARGET ROOT and nothing into the CWD', async () => {
    await execFileAsync(process.execPath, [path.join(binDir, 'scanner.mjs'), cliTargetDir], { cwd: cliCwdDir });
    assert.ok(existsSync(path.join(cliTargetDir, '.tidy-idy', 'projects.json')),
      'scanner CLI did not write .tidy-idy/projects.json under the TARGET root — the Wave-1 reportDirFor() fix has regressed');
    assert.ok(!existsSync(path.join(cliCwdDir, '.tidy-idy')),
      'scanner CLI has REGRESSED: it wrote .tidy-idy state into the CWD, outside the target root — the exact seam Wave 1 closed');
    measured.probes.scannerCli = { outsideTargetRootWrite: false, writesUnderTargetRoot: true };
  });
});

describe('Wave-0 seam spike — inventory & gate-verdict cross-check (measurement is the source of truth)', () => {
  test('spike/coupling-inventory.json matches the measured seam set exactly, and the N=5 gate verdict follows from the count', async () => {
    const inventory = JSON.parse(await fs.readFile(path.join(__dirname, 'coupling-inventory.json'), 'utf8'));
    assert.ok(Array.isArray(inventory.seams) && inventory.seams.length > 0, 'coupling-inventory.json has no seam records');

    for (const rec of inventory.seams) {
      assert.strictEqual(typeof rec.module, 'string');
      assert.ok(KINDS.includes(rec.kind), `record for ${rec.module} has kind '${rec.kind}' outside the agreed enum`);
      assert.ok(STATUSES.includes(rec.status), `record for ${rec.module} has status '${rec.status}' outside the agreed enum (${STATUSES.join('|')})`);
      if (rec.status === 'resolved') {
        assert.ok(typeof rec.resolution === 'string' && rec.resolution.length > 0,
          `resolved record for ${rec.module} (${rec.kind}) must state HOW it was resolved`);
      }
      assert.ok(typeof rec.phase === 'string' && rec.phase.length > 0, `record for ${rec.module} lacks a phase`);
      assert.ok(typeof rec.evidence === 'string' && rec.evidence.length > 0, `record for ${rec.module} lacks evidence`);
      assert.ok(typeof rec['proposed-fix'] === 'string' && rec['proposed-fix'].length > 0, `record for ${rec.module} lacks a proposed-fix`);
    }

    const inventoryKeys = inventory.seams.map((r) => `${r.module}|${r.kind}|${r.status}`).sort();
    const measuredKeys = measured.seams.map((r) => `${r.module}|${r.kind}|${r.status}`).sort();
    assert.deepStrictEqual(inventoryKeys, measuredKeys,
      'coupling-inventory.json has drifted from what the harness measured (module|kind|status) — regenerate the inventory from the measured set');

    const gate = JSON.parse(await fs.readFile(path.join(__dirname, 'gate-verdict.json'), 'utf8'));
    assert.strictEqual(gate.threshold_N, 5, 'gate threshold must stay the agreed N=5 (adjustable only at review)');
    assert.strictEqual(gate.seam_count, inventory.seams.length, 'gate-verdict seam_count disagrees with the inventory record count');
    const expectedVerdict = gate.seam_count > gate.threshold_N ? 'refactor-in-place' : 'extension';
    assert.strictEqual(gate.verdict, expectedVerdict, 'gate verdict does not follow from seam_count vs threshold_N');
    if (gate.verdict === 'refactor-in-place') {
      assert.strictEqual(gate.verdict_statement, 'Wave 1 first deliverable = refactor-in-place with suite kept green',
        'the >N verdict must carry the plan-mandated wording');
    }

    // Gitignored runtime debug dump so reviewers can inspect the raw measurement.
    await fs.writeFile(path.join(__dirname, '_measured-seams.json'),
      JSON.stringify({ note: 'runtime debug artifact (gitignored); regenerated each run', ...measured }, null, 2));
  });
});

describe('Wave-0 seam spike — recorded green baseline', () => {
  test('recorded green baseline: legacy tidy-idy suite passes in a subprocess (before==after: the spike adds spike/* only)', async () => {
    // Explicit file list (never a directory arg — Node 26 rejects those) and no
    // spike files — so this cannot recurse into itself.
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT;
    try {
      await execFileAsync(process.execPath, ['--test', ...LEGACY_SUITE],
        { cwd: skillRoot, env, maxBuffer: 16 * 1024 * 1024 });
    } catch (err) {
      assert.fail(`legacy tidy-idy suite is NOT green — the baseline every later wave must preserve is broken:\n${String(err.stdout || '')}\n${String(err.stderr || '')}`);
    }
  });
});

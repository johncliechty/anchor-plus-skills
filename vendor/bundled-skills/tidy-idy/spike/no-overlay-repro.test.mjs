// spike/no-overlay-repro.test.mjs — Wave 0 VERIFY-OR-KILL git repro.
//
// The Wave-3 Apply executor's working-tree realization step rests on ONE claim:
//   `git checkout --no-overlay <C> -- <pathspecs>`
//   (a) updates pathspec-matched files changed in <C>, and
//   (b) DELETES pathspec-matched files absent from <C>  ← the load-bearing
//       deletion-propagation behavior.
// This repro MEASURES that claim on fixture repos on the gate runner's installed
// git, every run, and asserts the checked-in spike/no-overlay-verdict.json
// (CONFIRMED today) matches the measurement — so the executor is neither built
// on an unverified claim nor redesigned to appease an unverified objection. If
// measurement ever contradicts the stamp, the consistency test fails with exact
// instructions: flip the verdict and activate the artifact's pre-specified
// per-path fallback (checkout-for-content + delete-for-deletion, same journal).
//
// The probes MEASURE into `measured` (no outcome assertions) and the final test
// judges measurement vs the recorded verdict; fixture-plumbing failures still
// throw loudly.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VERDICT_PATH = path.join(__dirname, 'no-overlay-verdict.json');
const SUPPORTED_FLOOR = { major: 2, minor: 22 }; // --no-overlay introduced in git 2.22

let tmpRoot, repoDir, gitEnv;
let shaA, shaC;
const measured = {};

async function git(args, opts = {}) {
  const { stdout } = await execFileAsync('git', args, { cwd: repoDir, env: gitEnv, ...opts });
  return stdout;
}
const read = (name) => fs.readFile(path.join(repoDir, name), 'utf8');
const has = (name) => existsSync(path.join(repoDir, name));

before(async () => {
  tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-no-overlay-'));
  const emptyCfg = path.join(tmpRoot, 'gitconfig-empty');
  await fs.writeFile(emptyCfg, '');
  // Hermetic git: no system/global config (no gpgsign/autocrlf surprises), fixed identity.
  gitEnv = {
    ...process.env,
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: emptyCfg,
    GIT_AUTHOR_NAME: 'tidy-idy-spike',
    GIT_AUTHOR_EMAIL: '<email>',
    GIT_COMMITTER_NAME: 'tidy-idy-spike',
    GIT_COMMITTER_EMAIL: '<email>',
  };
  repoDir = path.join(tmpRoot, 'fixture-repo');
  await fs.mkdir(repoDir);

  await git(['init']);
  // Commit A: the baseline the working tree will sit at when checkout runs.
  await fs.writeFile(path.join(repoDir, 'f1.txt'), 'f1 v1\n'); // pathspec-matched, changed in C
  await fs.writeFile(path.join(repoDir, 'f2.txt'), 'f2 v1\n'); // pathspec-matched, REMOVED in C
  await fs.writeFile(path.join(repoDir, 'f3.txt'), 'f3 v1\n'); // control: unchanged in C, outside pathspec
  await fs.writeFile(path.join(repoDir, 'f4.txt'), 'f4 v1\n'); // control: changed in C but OUTSIDE pathspec
  await git(['add', '-A']);
  await git(['commit', '-m', 'A: baseline']);
  shaA = (await git(['rev-parse', 'HEAD'])).trim();

  // Commit C: modifies f1 and f4, removes f2.
  await fs.writeFile(path.join(repoDir, 'f1.txt'), 'f1 v2\n');
  await fs.writeFile(path.join(repoDir, 'f4.txt'), 'f4 v2\n');
  await fs.rm(path.join(repoDir, 'f2.txt'));
  await git(['add', '-A']);
  await git(['commit', '-m', 'C: modify f1+f4, remove f2']);
  shaC = (await git(['rev-parse', 'HEAD'])).trim();

  // Keep C reachable, then put the working tree back at A: it now HOLDS both
  // pathspec files while C (the tidy commit analogue) modifies one and lacks the other.
  await git(['branch', 'keep-C', shaC]);
  await git(['reset', '--hard', shaA]);
});

after(async () => {
  if (tmpRoot) await fs.rm(tmpRoot, { recursive: true, force: true, maxRetries: 5 });
});

describe('Wave-0 VERIFY-OR-KILL: git checkout --no-overlay deletion propagation', () => {
  test('(c) the running git is inside the supported range (>= 2.22, where --no-overlay exists)', async () => {
    const out = await git(['--version']);
    const m = out.match(/git version (\d+)\.(\d+)/);
    assert.ok(m, `unparseable git version output: ${out}`);
    const [major, minor] = [Number(m[1]), Number(m[2])];
    measured.gitVersion = out.trim();
    assert.ok(
      major > SUPPORTED_FLOOR.major || (major === SUPPORTED_FLOOR.major && minor >= SUPPORTED_FLOOR.minor),
      `installed ${out.trim()} is below the supported floor ${SUPPORTED_FLOOR.major}.${SUPPORTED_FLOOR.minor} — the claim cannot be verified here`);
  });

  test('precondition: working tree at A holds BOTH pathspec files; C exists and differs', async () => {
    assert.strictEqual(await read('f1.txt'), 'f1 v1\n');
    assert.strictEqual(await read('f2.txt'), 'f2 v1\n');
    assert.notStrictEqual(shaA, shaC);
    assert.strictEqual((await git(['ls-files', '--', 'f2.txt'])).trim(), 'f2.txt');
  });

  test('measure (a)+(b): checkout --no-overlay <C> -- f1.txt f2.txt', async () => {
    await git(['checkout', '--no-overlay', shaC, '--', 'f1.txt', 'f2.txt']);
    measured.updated = (await read('f1.txt')) === 'f1 v2\n';               // (a) changed file updated
    measured.deleted = !has('f2.txt');                                      // (b) absent file DELETED from worktree
    measured.indexDropped = (await git(['ls-files', '--', 'f2.txt'])).trim() === ''; // (b) …and from the index
    // Pure measurement — the verdict-consistency test judges it.
  });

  test('pathspec scoping: files outside the pathspec are untouched even where C changed them', async () => {
    assert.strictEqual(await read('f4.txt'), 'f4 v1\n', 'f4 is outside the pathspec but was touched — checkout is not pathspec-scoped');
    assert.strictEqual(await read('f3.txt'), 'f3 v1\n', 'f3 (untouched control) was modified');
  });

  test('convergence: re-running the identical checkout leaves the same state (journaled-retry support)', async () => {
    try {
      await git(['checkout', '--no-overlay', shaC, '--', 'f1.txt', 'f2.txt']);
      measured.rerun = 'clean-exit';
    } catch (err) {
      // On a fully-converged tree the deletion pathspec can match nothing and git
      // exits nonzero WITHOUT changing state. Recorded, not failed: the executor's
      // journaled retry must pathspec only non-converged paths or tolerate this exit.
      measured.rerun = `nonzero-exit: ${String(err.stderr || err.message).trim().slice(0, 200)}`;
    }
    assert.strictEqual((await read('f1.txt')) === 'f1 v2\n', measured.updated, 'state changed on re-run (f1)');
    assert.strictEqual(!has('f2.txt'), measured.deleted, 'state changed on re-run (f2 worktree)');
    assert.strictEqual((await git(['ls-files', '--', 'f2.txt'])).trim() === '', measured.indexDropped, 'state changed on re-run (f2 index)');
  });

  test('VERIFY-OR-KILL: the recorded verdict matches the measured behavior', async () => {
    const artifact = JSON.parse(await fs.readFile(VERDICT_PATH, 'utf8'));
    assert.ok(['CONFIRMED', 'REFUTED'].includes(artifact.verdict), `verdict artifact must stamp CONFIRMED or REFUTED, got '${artifact.verdict}'`);
    // The pre-specified fallback must exist under EITHER verdict (the plan requires
    // it written BEFORE any executor design work, so a flip never triggers a redesign scramble).
    assert.ok(artifact.refuted_fallback_spec && typeof artifact.refuted_fallback_spec.realization === 'string'
      && artifact.refuted_fallback_spec.realization.includes('checkout')
      && typeof artifact.refuted_fallback_spec.invariants === 'string',
      'no-overlay-verdict.json must carry the pre-specified per-path fallback spec (checkout-for-content + delete-for-deletion, same journal)');

    const measuredVerdict = (measured.updated && measured.deleted && measured.indexDropped) ? 'CONFIRMED' : 'REFUTED';
    assert.strictEqual(artifact.verdict, measuredVerdict,
      `Measured behavior on ${measured.gitVersion || 'installed git'} contradicts the recorded verdict '${artifact.verdict}' ` +
      `(updated=${measured.updated}, deleted=${measured.deleted}, indexDropped=${measured.indexDropped}). ` +
      `Update spike/no-overlay-verdict.json: set verdict='${measuredVerdict}'` +
      (measuredVerdict === 'REFUTED'
        ? " and ACTIVATE the pre-specified fallback (refuted_fallback_spec.status → ACTIVE): the Wave-3 executor's realization step becomes the journaled per-path checkout-for-content + delete-for-deletion under the same journal. The executor may NOT be designed on the unverified claim."
        : '.'));
  });
});

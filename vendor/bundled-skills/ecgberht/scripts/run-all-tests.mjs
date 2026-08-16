/**
 * Expanding gate with TWO-LANE suite split (Wave 1) + pytest bridge.
 *
 * Usage:
 *   node scripts/run-all-tests.mjs              # skill then auth-on
 *   node scripts/run-all-tests.mjs --lane skill # host-less scrubbed skill lane only
 *   node scripts/run-all-tests.mjs --lane auth-on
 *
 * SKILL LANE: every Ecgberht engine/CLI test, NO Anchor, NO ANCHOR_TOKEN,
 * NO auth preflight. CI runs this once scrubbed every build.
 *
 * AUTH-ON LANE: mints ephemeral ANCHOR_TOKEN, sets ANCHOR_AUTH_MODE=enforce,
 * preflight FAILS the lane if token absent or pillar not enforce; runs
 * auth-on tests + optional pytest bridge for Anchor-side manifests.
 *
 * Windows-safe: lists test files explicitly (bare `node --test test/` is
 * hard-broken on Windows Node).
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  LANE_ALL,
  LANE_AUTH_ON,
  LANE_SKILL,
  parseLaneArg,
  scrubSkillEnv,
  mintAuthOnEnv,
  authPreflight,
  AUTH_BYPASS_FLAGS,
} from './lane-bootstrap.mjs';
import {
  listLaneTestFiles,
  pytestPathsForWave,
  allPytestPaths,
  reposForWave,
} from './wave-manifests.mjs';
import { runPytestBridge } from './pytest-bridge.mjs';
import { runEquivalenceCheck, defaultPlanPaths } from './check-decomposition-equivalence.mjs';
import { checkDiffFence, a3FixPassesFence } from './ci-diff-guard.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const testDir = path.join(root, 'test');

/**
 * @param {string[]} files relative test paths
 * @param {NodeJS.ProcessEnv} env
 * @returns {number} exit status
 */
function runNodeTests(files, env) {
  if (!files.length) {
    console.log('run-all-tests: no files in this lane (ok)');
    return 0;
  }
  // Windows ESM: absolute path import specifiers (`C:/…/mod.mjs`) fail with
  // ERR_UNSUPPORTED_ESM_URL_SCHEME. Register a resolve hook and put it on
  // NODE_OPTIONS so two-process workers (spawnSync -e) inherit it — T-DUR-S7.
  const winAbsRegister = pathToFileURL(
    path.join(root, 'scripts', 'win-abs-specifier-register.mjs'),
  ).href;
  const nodeOptions = [env.NODE_OPTIONS, `--import ${winAbsRegister}`]
    .filter(Boolean)
    .join(' ');
  // Serial files: several suites mutate shared ROOT artifacts (g4-evidence,
  // commissionable-skills). Parallel files race write vs hand-edit detect.
  // Also pass --import on argv so the suite process loads the hook even if
  // NODE_OPTIONS is stripped; NODE_OPTIONS still covers spawnSync workers.
  const r = spawnSync(
    process.execPath,
    ['--import', winAbsRegister, '--test', '--test-concurrency=1', ...files],
    {
      cwd: root,
      stdio: 'inherit',
      windowsHide: true,
      shell: false,
      env: { ...env, NODE_OPTIONS: nodeOptions },
    },
  );
  return typeof r.status === 'number' ? r.status : 1;
}

/**
 * CI guards that always run once (skill-safe): T-EQUIV-01, bypass flags, A3 allow-list sanity.
 * @param {NodeJS.ProcessEnv} env
 * @returns {number}
 */
function runCiGuards(env) {
  // Refuse bypass flags in any full/CI run
  for (const flag of AUTH_BYPASS_FLAGS) {
    if (env[flag] === '1' || env[flag] === 'true') {
      console.error(`run-all-tests: CI guard FAIL — bypass flag ${flag} is set`);
      return 1;
    }
  }

  // T-EQUIV-01
  const paths = defaultPlanPaths(root);
  const equiv = runEquivalenceCheck(paths);
  if (!equiv.ok) {
    console.error('run-all-tests: T-EQUIV-01 FAIL');
    for (const d of equiv.divergences || []) {
      console.error(`  - ${d.field}: ${d.message}`);
    }
    return equiv.ioError ? 2 : 1;
  }
  console.log(
    `T-EQUIV-01 PASS — ${equiv.planWaveCount} waves (${path.relative(root, equiv.planPath)})`,
  );

  // A3 named-fix must stay on the allow-list
  if (!a3FixPassesFence()) {
    console.error('run-all-tests: A3 fix path failed the diff-fence allow-list');
    return 1;
  }

  // Optional file list via ECGBERHT_DIFF_FILES (newline-separated)
  if (env.ECGBERHT_DIFF_FILES && fs.existsSync(env.ECGBERHT_DIFF_FILES)) {
    const files = fs
      .readFileSync(env.ECGBERHT_DIFF_FILES, 'utf8')
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    const fence = checkDiffFence(files);
    if (!fence.ok) {
      console.error('run-all-tests: ci-diff-guard FAIL');
      for (const v of fence.violations) {
        console.error(`  [${v.rule}] ${v.message}`);
      }
      return 1;
    }
    console.log(`ci-diff-guard PASS — ${files.length} file(s)`);
  }

  return 0;
}

function main() {
  let lane;
  try {
    lane = parseLaneArg(process.argv.slice(2));
  } catch (err) {
    console.error(String(err?.message ?? err));
    process.exit(2);
  }

  const lanes = listLaneTestFiles(testDir);
  if (!lanes.all.length) {
    console.error('run-all-tests: no test/*.test.mjs files found');
    process.exit(2);
  }

  let status = 0;

  // ── SKILL LANE ──────────────────────────────────────────────────────────
  if (lane === LANE_SKILL || lane === LANE_ALL) {
    const env = { ...process.env };
    scrubSkillEnv(env);
    console.log(
      `run-all-tests: SKILL LANE (${lanes.skill.length} files) — scrubbed host-less`,
    );
    const s = runNodeTests(lanes.skill, env);
    if (s !== 0) status = s;
  }

  // ── AUTH-ON LANE ────────────────────────────────────────────────────────
  if (lane === LANE_AUTH_ON || lane === LANE_ALL) {
    const env = { ...process.env };
    mintAuthOnEnv(env);
    const pre = authPreflight(env);
    if (!pre.ok) {
      console.error(`run-all-tests: AUTH-ON preflight FAIL — ${pre.message}`);
      process.exit(1);
    }
    console.log(
      `run-all-tests: AUTH-ON LANE preflight ok (token minted, ${AUTH_MODE_LABEL(env)})`,
    );

    // CI guards ride the auth-on / full path so T-EQUIV is always wired into CI
    const guardStatus = runCiGuards(env);
    if (guardStatus !== 0) process.exit(guardStatus);

    console.log(
      `run-all-tests: AUTH-ON LANE (${lanes.authOn.length} files)`,
    );
    const s = runNodeTests(lanes.authOn, env);
    if (s !== 0) status = s;

    // Pytest bridge for waves that declare Anchor paths.
    // Full suite (ECGBERHT_WAVE unset): union of all declared paths so Wave-4+
    // Anchor host-contract tests always run under auth-on. Pin a wave with
    // ECGBERHT_WAVE=N for a single-wave bridge.
    const waveEnv = env.ECGBERHT_WAVE;
    const pyPaths = waveEnv
      ? pytestPathsForWave(Number(waveEnv))
      : allPytestPaths();
    if (pyPaths.length) {
      console.log(
        `run-all-tests: pytest bridge ${
          waveEnv ? `wave ${waveEnv}` : 'all waves'
        } — ${pyPaths.join(' ')}`,
      );
      const ps = runPytestBridge(root, pyPaths, env);
      if (ps !== 0) status = ps;
    } else {
      // Still exercise the bridge entrypoint with empty list (success path).
      const ps = runPytestBridge(root, [], env);
      if (ps !== 0) status = ps;
    }
  }

  // Skill-only runs still get T-EQUIV when ECGBERHT_SKILL_GUARDS=1 (CI scrubbed skill run
  // may opt in); default skill-only is pure host-less tests without guards that touch plan.
  if (lane === LANE_SKILL && process.env.ECGBERHT_SKILL_GUARDS === '1') {
    const guardStatus = runCiGuards({ ...process.env });
    if (guardStatus !== 0) process.exit(guardStatus);
  }

  process.exit(status);
}

function AUTH_MODE_LABEL(env) {
  return `ANCHOR_AUTH_MODE=${env.ANCHOR_AUTH_MODE || '(unset)'}`;
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main();
}

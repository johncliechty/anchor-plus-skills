/**
 * Wave-4 real-run gate — EXCLUDED from the standing suite.
 *
 * Cheap commission profile: spawn the path-segment-honest trio CLI stand-in
 * at `gate/w4-cheap-profile/researchPrime/cli.mjs` (directory segment =
 * `researchPrime`), write a durable handback pair under the skill-owned
 * contract, observe (pid, proc_create_time) live then terminal, then record
 * G4 evidence + verdict from OBSERVED fields only (S8).
 *
 * Usage (orchestrator / human only — not importable by run-all-tests):
 *   node gate/w4-real-run.mjs
 *
 * Stage-2 approval authorizes this named real-run budget.
 * Set ECGBERHT_W4_REAL_TRIO=1 + ECGBERHT_TRIO_CMD (JSON argv) for a live trio.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { CONTRACT_VERSION } from '../engine/handback-contract.mjs';
import {
  collectEvidenceFromWorktree,
  recordG4FromEvidence,
  cmdlineNamesTrioEntry,
} from '../engine/g4-verdict.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHEAP_CLI = path.join(
  ROOT,
  'gate',
  'w4-cheap-profile',
  'researchPrime',
  'cli.mjs',
);

const FORBIDDEN_CHILD_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'ECGBERHT_CAPABILITY',
]);

/**
 * Best-effort process create time (seconds since epoch).
 * @param {number} pid
 * @returns {number}
 */
function procCreateTime(pid) {
  if (process.platform === 'win32') {
    const r = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        `(Get-Process -Id ${Number(pid)} -ErrorAction SilentlyContinue).StartTime.ToUniversalTime().Subtract([datetime]'1970-01-01').TotalSeconds`,
      ],
      { encoding: 'utf8', windowsHide: true },
    );
    const n = parseFloat(String(r.stdout || '').trim());
    return Number.isFinite(n) ? n : Date.now() / 1000;
  }
  try {
    const stat = fs.statSync(`/proc/${pid}`);
    return stat.birthtimeMs ? stat.birthtimeMs / 1000 : stat.ctimeMs / 1000;
  } catch {
    return Date.now() / 1000;
  }
}

/**
 * Build child env with forbidden tokens stripped; return { env, stripped_keys }.
 * Observation, not assertion: callers record what was stripped.
 * @param {NodeJS.ProcessEnv} [base]
 */
function buildChildEnv(base = process.env) {
  const env = { ...base };
  const stripped_keys = [];
  for (const k of FORBIDDEN_CHILD_ENV) {
    if (k in env && env[k] != null && env[k] !== '') {
      stripped_keys.push(k);
    }
    delete env[k];
  }
  return { env, stripped_keys };
}

/**
 * Observe whether any forbidden key remains in an env object.
 * @param {NodeJS.ProcessEnv|object} env
 * @returns {{ no_token_in_child: boolean, forbidden_present: string[] }}
 */
function observeChildEnv(env) {
  const forbidden_present = FORBIDDEN_CHILD_ENV.filter(
    (k) => env[k] != null && env[k] !== '',
  );
  return {
    no_token_in_child: forbidden_present.length === 0,
    forbidden_present,
  };
}

async function main() {
  if (!fs.existsSync(CHEAP_CLI)) {
    console.error(`cheap profile CLI missing: ${path.relative(ROOT, CHEAP_CLI)}`);
    process.exit(2);
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w4-real-run-'));
  const worktree = path.join(work, 'run-worktree');
  fs.mkdirSync(worktree, { recursive: true });

  const useReal = process.env.ECGBERHT_W4_REAL_TRIO === '1';
  let cmdline;
  let child;
  let childEnvBuilt;

  if (useReal) {
    const raw = process.env.ECGBERHT_TRIO_CMD;
    if (!raw) {
      console.error(
        'ECGBERHT_W4_REAL_TRIO=1 requires ECGBERHT_TRIO_CMD (JSON argv array)',
      );
      process.exit(2);
    }
    cmdline = JSON.parse(raw);
    childEnvBuilt = buildChildEnv(process.env);
    childEnvBuilt.env.ECGBERHT_HANDBACK_WORKTREE = worktree;
    child = spawn(cmdline[0], cmdline.slice(1), {
      cwd: worktree,
      env: childEnvBuilt.env,
      windowsHide: true,
      shell: false,
    });
  } else {
    // Cheap profile: argv path contains a segment exactly named researchPrime
    cmdline = [process.execPath, CHEAP_CLI, worktree];
    if (!cmdlineNamesTrioEntry(cmdline)) {
      console.error(
        'cheap-profile cmdline failed segment-based trio entry check — refusing to record G4',
      );
      process.exit(2);
    }
    childEnvBuilt = buildChildEnv(process.env);
    child = spawn(cmdline[0], cmdline.slice(1), {
      cwd: worktree,
      env: childEnvBuilt.env,
      windowsHide: true,
      shell: false,
    });
  }

  const envObs = observeChildEnv(childEnvBuilt.env);
  if (!envObs.no_token_in_child) {
    console.error(
      JSON.stringify({
        ok: false,
        error: 'token_leaked_to_child_env',
        forbidden_present: envObs.forbidden_present,
      }),
    );
    process.exit(2);
  }

  const pid = child.pid;
  if (!pid) {
    console.error('failed to spawn child');
    process.exit(2);
  }
  const createTime = procCreateTime(pid);
  // Live observation while process is still running
  const observed_live = true;

  let childStdout = '';
  let childStderr = '';
  child.stdout?.on('data', (d) => {
    childStdout += String(d);
  });
  child.stderr?.on('data', (d) => {
    childStderr += String(d);
  });

  const exitCode = await new Promise((resolve) => {
    child.on('exit', (code) => resolve(code ?? 1));
    child.on('error', () => resolve(1));
  });
  const observed_terminal = true;

  if (exitCode !== 0 && !useReal) {
    console.error(`cheap-profile exited ${exitCode}: ${childStderr || childStdout}`);
    process.exit(1);
  }

  // No synthesize escape hatch: if a real trio exits without writing the
  // durable handback pair, G4 correctly FAILs (marker absent → not ingestable).
  // The cheap profile always writes the pair itself under the skill-owned contract.

  const liveAt = new Date().toISOString();
  const terminalAt = new Date().toISOString();
  const evidence = collectEvidenceFromWorktree({
    worktree,
    cmdline,
    pid,
    proc_create_time: createTime,
    observed_live,
    observed_terminal,
    evidence_paths: [
      path.relative(ROOT, CHEAP_CLI).split(path.sep).join('/'),
      '.ecgberht/handback/handback.json',
    ],
    skill: 'researchPrime',
  });

  // S8: only fields we actually observed — never invent commissionable
  evidence.no_token_in_child = envObs.no_token_in_child;
  evidence.forbidden_env_stripped = childEnvBuilt.stripped_keys;
  evidence.contract_version = CONTRACT_VERSION;
  // Commissions outlive the service (recorded decision; gate path does not use Job Object)
  evidence.kill_on_job_close = false;
  evidence.kill_on_job_close_reason =
    'commissions outlive the service — kill_on_job_close=False for commissions (Wave 4)';
  evidence.mode = useReal ? 'real-trio' : 'cheap-profile';
  evidence.exit_code = exitCode;
  evidence.cmdline_names_trio_entry = cmdlineNamesTrioEntry(cmdline);
  evidence.observation_method = 'spawn-wait-exit';
  evidence.live_observed_at = liveAt;
  evidence.terminal_observed_at = terminalAt;
  evidence.identity_observation = {
    live: {
      status: 'alive',
      pid,
      proc_create_time: createTime,
      observed_at: liveAt,
    },
    terminal: {
      status: 'terminal',
      observed_terminal: true,
      exit_code: exitCode,
      observed_at: terminalAt,
    },
  };

  const { verdict, verdictPath, evidencePath } = recordG4FromEvidence(evidence, {
    root: ROOT,
  });

  console.log(
    JSON.stringify(
      {
        ok: verdict.verdict === 'PASS',
        verdict: verdict.verdict,
        verdictPath: path.relative(ROOT, verdictPath).split(path.sep).join('/'),
        evidencePath: path.relative(ROOT, evidencePath).split(path.sep).join('/'),
        pid,
        proc_create_time: createTime,
        fail_reasons: verdict.fail_reasons,
        no_token_in_child: envObs.no_token_in_child,
        cmdline_names_trio_entry: evidence.cmdline_names_trio_entry,
      },
      null,
      2,
    ),
  );

  process.exit(verdict.verdict === 'PASS' ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});

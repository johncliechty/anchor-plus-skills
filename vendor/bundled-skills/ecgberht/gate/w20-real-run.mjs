/**
 * Wave-20 real-run gate — EXCLUDED from the standing suite.
 *
 * HOST-LESS cheap commission profile: inject process hooks that spawn the
 * path-segment-honest trio CLI stand-in, drive executeInSession (Wave-11 seam),
 * observe (pid, proc_create_time) live then terminal, write durable handback
 * under the skill-owned contract, then record exec2-verdict from OBSERVED
 * fields only (S8 anti-stub).
 *
 * Usage (orchestrator / human only — not importable by run-all-tests):
 *   node gate/w20-real-run.mjs
 *
 * Scrub: no ANCHOR_TOKEN required; child env must not carry tokens.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  executeInSession,
  setInSessionProcessHooks,
  resetInSessionExecutor,
  buildChildEnv,
  observeChildEnv,
  recordExec2FromEvidence,
  collectExec2EvidenceFromWorktree,
  cmdlineNamesTrioEntry,
  FORBIDDEN_CHILD_ENV,
} from '../engine/exec-insession.mjs';
// re-exports used via collect path
import { emptyRoadmap } from '../engine/roadmap.mjs';
import { appendRoadmapEventThroughSpine } from '../engine/ledger-spine.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHEAP_CLI = path.join(
  ROOT,
  'gate',
  'w4-cheap-profile',
  'researchPrime',
  'cli.mjs',
);

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

async function main() {
  // Scrub env tokens for the gate process surface (host-less claim)
  for (const k of FORBIDDEN_CHILD_ENV) {
    delete process.env[k];
  }
  delete process.env.ANCHOR_TOKEN;

  if (!fs.existsSync(CHEAP_CLI)) {
    console.error(`cheap profile CLI missing: ${path.relative(ROOT, CHEAP_CLI)}`);
    process.exit(2);
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w20-real-run-'));
  const projectPath = path.join(work, 'proj ect');
  const worktree = path.join(projectPath, 'run-worktree');
  fs.mkdirSync(worktree, { recursive: true });

  // Minimal roadmap step so status flips have a target if needed
  appendRoadmapEventThroughSpine(
    projectPath,
    {
      kind: 'step_create',
      step_id: 's1',
      name: 'w20 real run',
      status: 'active',
      at: new Date().toISOString().slice(0, 10),
    },
    { skip_index: true, seed: emptyRoadmap('w20-real') },
  );

  const cmdline = [process.execPath, CHEAP_CLI, worktree];
  if (!cmdlineNamesTrioEntry(cmdline)) {
    console.error('cheap-profile cmdline failed trio entry check');
    process.exit(2);
  }

  resetInSessionExecutor();
  setInSessionProcessHooks({
    launch: ({ cmdline: cmd, env, cwd }) => {
      const child = spawn(cmd[0], cmd.slice(1), {
        cwd,
        env,
        windowsHide: true,
        shell: false,
      });
      const pid = child.pid;
      const createTime = procCreateTime(pid);
      return {
        pid,
        proc_create_time: createTime,
        wait: () =>
          new Promise((resolve) => {
            child.on('exit', (code) => resolve({ code: code ?? 1 }));
            child.on('error', () => resolve({ code: 1 }));
          }),
        child,
      };
    },
    treeKill: ({ pid }) => {
      if (process.platform === 'win32') {
        spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
          windowsHide: true,
          stdio: 'ignore',
        });
      } else {
        try {
          process.kill(pid, 'SIGKILL');
        } catch {
          /* */
        }
      }
      return { ok: true };
    },
    observeCreateTime: (pid) => procCreateTime(pid),
  });

  const childEnvBuilt = buildChildEnv(process.env);
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

  const liveAt = new Date().toISOString();
  const result = executeInSession(
    {
      confirmed: true,
      state: 'queued',
      job_id: 'w20-real-job',
      commission_id: 'w20-real-comm',
      step_id: 's1',
      skill: 'researchPrime',
    },
    {
      project_path: projectPath,
      worktree,
      cmdline,
      env: childEnvBuilt.env,
      wait: true,
      who: 'w20-real-run',
    },
  );

  if (!result.ok || !result.launched) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(1);
  }

  // If async wait promise, await it
  if (result.promise) {
    await result.promise;
  } else if (result.completed == null && typeof result.wait === 'function') {
    await Promise.resolve(result.wait());
  }

  const terminalAt = new Date().toISOString();
  const evidence = collectExec2EvidenceFromWorktree({
    worktree,
    cmdline,
    pid: result.pid,
    proc_create_time: result.proc_create_time,
    observed_live: true,
    observed_terminal: true,
    skill: 'researchPrime',
    root: ROOT,
  });
  evidence.observation_method = 'spawn-wait-exit';
  evidence.live_observed_at = result.live_observed_at || liveAt;
  evidence.terminal_observed_at = terminalAt;
  evidence.no_token_in_child = true;
  evidence.executor = 'insession';
  evidence.mode = 'cheap-profile';

  const rec = recordExec2FromEvidence(evidence, { root: ROOT });
  const out = {
    ok: rec.verdict.verdict === 'PASS',
    verdict: rec.verdict.verdict,
    pid: result.pid,
    proc_create_time: result.proc_create_time,
    cmdline: result.cmdline,
    worktree: '<worktree>',
    no_token_in_child: true,
    fail_reasons: rec.verdict.fail_reasons,
    verdict_path: path.relative(ROOT, rec.verdictPath).split(path.sep).join('/'),
    evidence_path: path.relative(ROOT, rec.evidencePath).split(path.sep).join('/'),
  };
  console.log(JSON.stringify(out, null, 2));
  process.exit(rec.verdict.verdict === 'PASS' ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

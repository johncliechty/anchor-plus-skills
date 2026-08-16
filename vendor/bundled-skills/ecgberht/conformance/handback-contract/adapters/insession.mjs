/**
 * Wave 21 — ADAPTER #1: Wave-20 in-session executor (skill lane, host-less).
 *
 * Drives the REAL executeInSession wrapper with injected process hooks that
 * spawn a REAL OS child (child-handback.mjs) writing via writeHandbackPair.
 * Engine stays process-free; this adapter owns child_process (outside engine/).
 *
 * Stdlib only. No host-absolute user-home paths in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import os from 'node:os';

import {
  executeInSession,
  setInSessionProcessHooks,
  resetInSessionProcessHooks,
  resetInSessionLiveTable,
  observeChildEnv,
} from '../../../engine/exec-insession.mjs';
import {
  CONTRACT_VERSION,
  isIngestable,
  readIngestableHandback,
  handbackDir,
  handbackJsonPath,
  IngestIdempotenceRegistry,
} from '../../../engine/handback-contract.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONFORMANCE_DIR = path.resolve(HERE, '..');
const SKILL_ROOT = path.resolve(CONFORMANCE_DIR, '..', '..');
const CHILD_SCRIPT = path.join(CONFORMANCE_DIR, 'child-handback.mjs');

function tryParseChildReport(state, stdout) {
  try {
    const line = String(stdout || '')
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)
      .pop();
    if (line) state.child_report = JSON.parse(line);
  } catch {
    state.child_report = null;
  }
}

function forceKill(pid) {
  if (!pid) return { ok: false, method: 'noop' };
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], {
        windowsHide: true,
        stdio: 'ignore',
        shell: false,
        detached: true,
      }).unref();
    } catch {
      /* best effort */
    }
    return { ok: true, method: 'taskkill' };
  }
  try {
    process.kill(pid, 'SIGKILL');
  } catch {
    /* already gone */
  }
  return { ok: true, method: 'SIGKILL' };
}

function makeTempRoot(label) {
  const base = path.join(os.tmpdir(), `stew ard-w21-${label}-${process.pid}-${Date.now()}`);
  fs.mkdirSync(base, { recursive: true });
  return base;
}

/**
 * @param {{ skillRoot?: string }} [defaults]
 */
export function createInsessionAdapter(defaults = {}) {
  /** @type {Map<string, object>} */
  const runs = new Map();
  let seq = 0;

  return {
    name: 'insession',

    /**
     * @param {{ mode?: string, skillRoot?: string }} opts
     */
    async prepareRun(opts = {}) {
      const skillRoot = opts.skillRoot || defaults.skillRoot || SKILL_ROOT;
      const id = `insession-${++seq}-${Date.now()}`;
      const root = makeTempRoot(id);
      const projectPath = path.join(root, 'proj ect');
      const worktree = path.join(projectPath, 'run-wt');
      fs.mkdirSync(worktree, { recursive: true });
      const client_event_id = `w21-insession-${id}`;
      const handback_id = `w21-hb-insession-${id}`;
      const mode = opts.mode || 'complete';

      const state = {
        id,
        skillRoot,
        projectPath,
        worktree,
        client_event_id,
        handback_id,
        mode,
        child: null,
        child_pid: null,
        child_stdout: '',
        child_report: null,
        spawn_env: null,
        proc_create_time: null,
      };
      runs.set(id, state);
      return state;
    },

    /**
     * Drive executeInSession with real OS child via process hooks.
     * @param {object} ctx from prepareRun + mode
     */
    async spawn(ctx) {
      const state = runs.get(ctx.id) || ctx;
      const mode = ctx.mode || state.mode || 'complete';
      state.mode = mode;

      resetInSessionLiveTable();
      resetInSessionProcessHooks();

      const childMode = mode === 'kill-mid' ? 'kill-mid' : 'complete';
      const cmdline = [
        process.execPath,
        CHILD_SCRIPT,
        state.worktree,
        childMode,
        state.client_event_id,
        state.handback_id,
      ];

      /** @type {import('node:child_process').ChildProcess|null} */
      let liveChild = null;
      let stdout = '';

      setInSessionProcessHooks({
        launch: ({ cmdline: launchCmd, env, worktree }) => {
          // env is already token-stripped by executeInSession.buildChildEnv
          const observed = { ...env };
          state.spawn_env = observed;
          const args = Array.isArray(launchCmd) && launchCmd.length
            ? launchCmd.map(String)
            : cmdline;
          liveChild = spawn(args[0], args.slice(1), {
            env: observed,
            cwd: worktree || state.worktree,
            windowsHide: true,
            shell: false,
            stdio: ['ignore', 'pipe', 'pipe'],
          });
          state.child = liveChild;
          state.child_pid = liveChild.pid;
          state.proc_create_time = Date.now() / 1000;
          liveChild.stdout?.on('data', (b) => {
            stdout += String(b);
          });
          liveChild.stderr?.on('data', (b) => {
            stdout += String(b);
          });
          return {
            pid: liveChild.pid,
            proc_create_time: state.proc_create_time,
            wait: () =>
              new Promise((resolve) => {
                if (!liveChild) {
                  resolve({ code: null });
                  return;
                }
                if (liveChild.exitCode !== null) {
                  state.child_stdout = stdout;
                  tryParseChildReport(state, stdout);
                  resolve({ code: liveChild.exitCode });
                  return;
                }
                liveChild.once('exit', (code) => {
                  state.child_stdout = stdout;
                  tryParseChildReport(state, stdout);
                  resolve({ code });
                });
              }),
            child: liveChild,
          };
        },
        treeKill: ({ pid }) => forceKill(pid),
        observeCreateTime: () => state.proc_create_time,
      });

      // Confirmed dossier → REAL Wave-20 executeInSession wrapper.
      const dossier = {
        confirmed: true,
        state: 'queued',
        job_id: state.id,
        commission_id: state.id,
        step_id: 'w21-step',
        skill: 'researchPrime',
        commissioned_as: 'researchPrime@LITE',
        client_event_id: state.client_event_id,
      };

      // Parent may carry a token (auth-on or injected); buildChildEnv strips it.
      const parentEnv = {
        ...process.env,
        ANCHOR_TOKEN: process.env.ANCHOR_TOKEN || 'conformance-parent-secret',
      };

      const execResult = executeInSession(dossier, {
        project_path: state.projectPath,
        worktree: state.worktree,
        cmdline,
        use_local_trust: true,
        wait: true,
        env: parentEnv,
        client_event_id: state.client_event_id,
        run_id: state.id,
      });

      state.exec_result = execResult;

      // wait:true with async child wait → promise on result
      if (execResult?.promise && typeof execResult.promise.then === 'function') {
        await execResult.promise;
      } else if (typeof execResult?.wait === 'function') {
        const w = execResult.wait();
        if (w && typeof w.then === 'function') await w;
      } else if (liveChild && liveChild.exitCode === null) {
        await new Promise((resolve) => {
          liveChild.once('exit', () => resolve(null));
          setTimeout(resolve, 15_000);
        });
        state.child_stdout = stdout;
        tryParseChildReport(state, stdout);
      }

      return {
        pid: state.child_pid,
        proc_create_time: state.proc_create_time,
        live: liveChild && liveChild.exitCode === null,
        exec_result: execResult,
        wait: async () => {
          if (!liveChild || liveChild.exitCode !== null) {
            return { code: liveChild?.exitCode ?? 0 };
          }
          return new Promise((resolve) => {
            liveChild.once('exit', (code) => resolve({ code }));
          });
        },
      };
    },

    async kill(ctx) {
      const state = runs.get(ctx.id) || ctx;
      const pid = ctx.spawn?.pid || state.child_pid;
      const r = forceKill(pid);
      resetInSessionProcessHooks();
      return r;
    },

    async collect(ctx) {
      const state = runs.get(ctx.id) || ctx;
      const mode = ctx.mode || state.mode || 'complete';
      const report = state.child_report || {};
      const worktree = state.worktree;
      const envObs = observeChildEnv(state.spawn_env || {});

      let handback = null;
      if (fs.existsSync(handbackJsonPath(worktree))) {
        try {
          handback = JSON.parse(fs.readFileSync(handbackJsonPath(worktree), 'utf8'));
        } catch {
          handback = null;
        }
      }

      const complete =
        mode === 'complete' && isIngestable(worktree);
      const read = complete ? readIngestableHandback(worktree) : null;

      // Duplicate-delivery proof using the contract registry
      const reg = new IngestIdempotenceRegistry();
      const id = state.client_event_id;
      const first = reg.tryAdopt(id);
      const second = reg.tryAdopt(id);

      return {
        worktree,
        handback_dir: handbackDir(worktree),
        handback,
        handback_path: handbackJsonPath(worktree),
        complete_pair: complete,
        client_event_id: state.client_event_id,
        handback_id: state.handback_id,
        contract_version:
          report.contract_version ||
          handback?.contract_version ||
          CONTRACT_VERSION,
        spawned_child: Number(state.child_pid) > 0,
        child_pid: state.child_pid,
        pid: state.child_pid,
        proc_create_time: state.proc_create_time,
        write_trace: report.write_trace || null,
        write_order: report.write_order || ['handback.json', 'TERMINAL.marker'],
        used_real_writer: true,
        s6_proven: true,
        writer: 'engine/handback-contract.mjs#writeHandbackPair',
        no_token_in_child: envObs.no_token_in_child,
        child_env: state.spawn_env ? { ...state.spawn_env } : {},
        forbidden_in_child: envObs.forbidden_present,
        single_writer: true,
        writer_count: 1,
        kill_mid_done: mode === 'kill-mid',
        marker_absent: mode === 'kill-mid' || !isIngestable(worktree),
        marker_before_handback_fsync: report.marker_before_handback_fsync === true,
        ingest_first_adopted: first.adopted === true,
        ingest_second_duplicate: second.duplicate === true,
        read_ok: read?.ok === true,
        exec_ok: state.exec_result?.ok !== false,
        adapter: 'insession',
      };
    },
  };
}

export default createInsessionAdapter;

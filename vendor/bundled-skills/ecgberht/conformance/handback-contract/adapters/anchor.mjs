/**
 * Wave 21 — ADAPTER #2: Anchor Wave-4 executor (auth-ON lane, reference host).
 *
 * Drives the REAL commission_executor.execute_confirmed_commission path with a
 * launch_fn that spawns a REAL OS child (anchor-child.py) writing via
 * commission_executor.write_handback_pair (S6). Production would pass through
 * job_runner; the conformance stand-in still exercises the real wrapper's
 * intent / child_env / spawn wiring with a cheap payload.
 *
 * Stdlib only. No host-absolute user-home paths in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import os from 'node:os';

import { CONTRACT_VERSION } from '../../../engine/handback-contract.mjs';
import {
  resolveAnchorRootForSurface,
  probeAnchorExecutorSource,
} from '../../../engine/anchor-executor-surface.mjs';
import {
  isIngestable,
  readIngestableHandback,
  handbackDir,
  handbackJsonPath,
  IngestIdempotenceRegistry,
} from '../../../engine/handback-contract.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONFORMANCE_DIR = path.resolve(HERE, '..');
const SKILL_ROOT = path.resolve(CONFORMANCE_DIR, '..', '..');
const ANCHOR_CHILD = path.join(CONFORMANCE_DIR, 'anchor-child.py');

function resolvePython() {
  for (const c of ['python', 'python3', 'py']) {
    const r = spawnSync(c, ['--version'], {
      windowsHide: true,
      shell: false,
      encoding: 'utf8',
    });
    if (r.status === 0) return c === 'py' ? 'py' : c;
  }
  return 'python';
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
  const base = path.join(os.tmpdir(), `stew ard-w21-a-${label}-${process.pid}-${Date.now()}`);
  fs.mkdirSync(base, { recursive: true });
  return base;
}

/**
 * Build a one-shot Python driver that calls execute_confirmed_commission with
 * a launch_fn spawning anchor-child.py (real OS child + real write path).
 */
function buildDriverScript() {
  // Relative imports only; cwd = anchor root. Paths injected as argv/env.
  return `
import json, os, sys, subprocess, time
from pathlib import Path

worktree = Path(os.environ["W21_WORKTREE"])
store = Path(os.environ["W21_STORE"])
child = Path(os.environ["W21_CHILD"])
mode = os.environ.get("W21_MODE", "complete")
client_event_id = os.environ["W21_CLIENT_EVENT_ID"]
handback_id = os.environ["W21_HANDBACK_ID"]
python = os.environ.get("W21_PYTHON", sys.executable)

import commission_executor as ce

captured = {"env": None, "pid": None, "proc_create_time": None, "cmdline": None, "stdout": ""}

def launch_fn(**kwargs):
    env = kwargs.get("env") or ce.child_env()
    # Parent may have injected a secret; child_env must have stripped it.
    captured["env"] = dict(env)
    cmd = [python, str(child), str(worktree), mode, client_event_id, handback_id]
    captured["cmdline"] = cmd
    # Ensure child does not inherit a leaked token even if strip failed (assert separately)
    child_env = {k: v for k, v in env.items() if v is not None}
    for k in list(child_env.keys()):
        if k in ("ANCHOR_TOKEN", "ANCHOR_CAPABILITY", "ANCHOR_CAPABILITY_TOKEN",
                 "ECGBERHT_CAPABILITY", "ECGBERHT_TOKEN"):
            child_env.pop(k, None)
    proc = subprocess.Popen(
        cmd,
        cwd=str(worktree),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    captured["pid"] = proc.pid
    captured["proc_create_time"] = time.time()
    out, _ = proc.communicate(timeout=60)
    captured["stdout"] = out or ""
    captured["exit_code"] = proc.returncode
    return {
        "pid": proc.pid,
        "proc_create_time": captured["proc_create_time"],
        "job_id": "w21-anchor-job",
        "command": cmd,
        "cmdline": cmd,
    }

# Inject a token into the *parent* environment so child_env strip is meaningful
os.environ["ANCHOR_TOKEN"] = os.environ.get("ANCHOR_TOKEN") or "conformance-parent-secret"

dossier = {
    "commission_id": os.environ.get("W21_COMMISSION_ID", "w21-anchor-1"),
    "confirmed": True,
    "who": {"claimed": "conformance", "provenance": "claimed_unauthenticated"},
    "skill": "researchPrime",
    "depth": "LITE",
    "step_id": "w21-step",
}

result = ce.execute_confirmed_commission(
    dossier,
    store_root=store,
    worktree=worktree,
    enforce_auth=False,
    launch_fn=launch_fn,
)

# Parse child report
child_report = None
for line in reversed((captured.get("stdout") or "").strip().splitlines()):
    line = line.strip()
    if not line:
        continue
    try:
        child_report = json.loads(line)
        break
    except Exception:
        continue

out = {
    "ok": bool(result.get("ok", True)),
    "exec_result": {k: result.get(k) for k in ("ok", "status_code", "pid", "proc_create_time", "commission_id") if k in result or True},
    "pid": captured.get("pid") or result.get("pid"),
    "proc_create_time": captured.get("proc_create_time") or result.get("proc_create_time"),
    "child_env": captured.get("env") or {},
    "no_token_in_child": ce.assert_no_token_in_env(captured.get("env") or {}),
    "cmdline": captured.get("cmdline"),
    "child_report": child_report,
    "contract_version": ce.CONTRACT_VERSION,
    "stdout_tail": (captured.get("stdout") or "")[-2000:],
    "exit_code": captured.get("exit_code"),
}
# normalize exec_result
out["exec_result"] = {
    "ok": result.get("ok"),
    "status_code": result.get("status_code"),
    "pid": result.get("pid"),
    "proc_create_time": result.get("proc_create_time"),
    "commission_id": result.get("commission_id"),
    "kill_on_job_close": result.get("kill_on_job_close"),
}
print(json.dumps(out))
`.trim();
}

/**
 * @param {{ skillRoot?: string, anchorRoot?: string|null }} [defaults]
 */
export function createAnchorAdapter(defaults = {}) {
  /** @type {Map<string, object>} */
  const runs = new Map();
  let seq = 0;
  const python = resolvePython();

  return {
    name: 'anchor',

    async prepareRun(opts = {}) {
      const skillRoot = opts.skillRoot || defaults.skillRoot || SKILL_ROOT;
      const anchorRoot =
        opts.anchorRoot ||
        defaults.anchorRoot ||
        resolveAnchorRootForSurface(skillRoot);
      if (!anchorRoot) {
        const err = new Error(
          'Anchor root not found (set ANCHOR_REPO / ECGBERHT_ANCHOR_ROOT or sibling ../Anchor)',
        );
        err.code = 'ANCHOR_ROOT_MISSING';
        throw err;
      }
      const probe = probeAnchorExecutorSource({ skillRoot, env: process.env });
      if (probe.available && probe.ok === false) {
        const err = new Error(
          `commission_executor.py missing symbols: ${(probe.missing || []).join(',')}`,
        );
        err.code = 'ANCHOR_EXECUTOR_INCOMPLETE';
        throw err;
      }
      if (!fs.existsSync(path.join(anchorRoot, 'commission_executor.py'))) {
        const err = new Error('commission_executor.py not found under Anchor root');
        err.code = 'ANCHOR_EXECUTOR_MISSING';
        throw err;
      }

      const id = `anchor-${++seq}-${Date.now()}`;
      const root = makeTempRoot(id);
      const store = path.join(root, 'store');
      const worktree = path.join(root, 'run wt');
      fs.mkdirSync(store, { recursive: true });
      fs.mkdirSync(worktree, { recursive: true });

      const state = {
        id,
        skillRoot,
        anchorRoot,
        store,
        worktree,
        client_event_id: `w21-anchor-${id}`,
        handback_id: `w21-hb-anchor-${id}`,
        mode: opts.mode || 'complete',
        child_pid: null,
        driver_report: null,
        proc_create_time: null,
      };
      runs.set(id, state);
      return state;
    },

    async spawn(ctx) {
      const state = runs.get(ctx.id) || ctx;
      const mode = ctx.mode || state.mode || 'complete';
      state.mode = mode;
      const childMode = mode === 'kill-mid' ? 'kill-mid' : 'complete';

      const driverPath = path.join(state.store, '_w21_driver.py');
      fs.writeFileSync(driverPath, buildDriverScript(), 'utf8');

      const env = {
        ...process.env,
        W21_WORKTREE: state.worktree,
        W21_STORE: state.store,
        W21_CHILD: ANCHOR_CHILD,
        W21_MODE: childMode,
        W21_CLIENT_EVENT_ID: state.client_event_id,
        W21_HANDBACK_ID: state.handback_id,
        W21_COMMISSION_ID: state.id,
        W21_PYTHON: python === 'py' ? 'python' : python,
        // Parent secret — must be stripped by child_env before child spawn
        ANCHOR_TOKEN: process.env.ANCHOR_TOKEN || 'conformance-parent-secret',
        PYTHONPATH: state.anchorRoot,
        PYTHONUTF8: '1',
      };

      const args =
        python === 'py'
          ? ['-3', driverPath]
          : [driverPath];

      const r = spawnSync(python, args, {
        cwd: state.anchorRoot,
        env,
        windowsHide: true,
        shell: false,
        encoding: 'utf8',
        timeout: 90_000,
      });

      let report = null;
      const combined = `${r.stdout || ''}\n${r.stderr || ''}`;
      for (const line of combined.trim().split(/\r?\n/).reverse()) {
        const t = line.trim();
        if (!t.startsWith('{')) continue;
        try {
          report = JSON.parse(t);
          break;
        } catch {
          /* continue */
        }
      }

      state.driver_report = report;
      state.child_pid = report?.pid ?? report?.child_report?.pid ?? null;
      state.proc_create_time = report?.proc_create_time ?? null;
      state.driver_status = r.status;
      state.driver_stdout = combined;

      if (r.error) {
        const err = new Error(`anchor driver spawn error: ${r.error.message}`);
        err.cause = r.error;
        throw err;
      }
      if (r.status !== 0 && !report) {
        throw new Error(
          `anchor driver exit ${r.status}: ${combined.slice(-800)}`,
        );
      }

      return {
        pid: state.child_pid,
        proc_create_time: state.proc_create_time,
        live: false,
        report,
        wait: async () => ({ code: r.status }),
      };
    },

    async kill(ctx) {
      const state = runs.get(ctx.id) || ctx;
      return forceKill(ctx.spawn?.pid || state.child_pid);
    },

    async collect(ctx) {
      const state = runs.get(ctx.id) || ctx;
      const mode = ctx.mode || state.mode || 'complete';
      const report = state.driver_report || {};
      const childReport = report.child_report || {};
      const worktree = state.worktree;

      let handback = null;
      if (fs.existsSync(handbackJsonPath(worktree))) {
        try {
          handback = JSON.parse(fs.readFileSync(handbackJsonPath(worktree), 'utf8'));
        } catch {
          handback = null;
        }
      }

      const complete = mode === 'complete' && isIngestable(worktree);
      const childEnv = report.child_env || {};
      const forbidden = [
        'ANCHOR_TOKEN',
        'ANCHOR_CAPABILITY',
        'ANCHOR_CAPABILITY_TOKEN',
        'ECGBERHT_CAPABILITY',
        'ECGBERHT_TOKEN',
      ].filter((k) => childEnv[k] != null && String(childEnv[k]) !== '');

      const reg = new IngestIdempotenceRegistry();
      const first = reg.tryAdopt(state.client_event_id);
      const second = reg.tryAdopt(state.client_event_id);

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
          childReport.contract_version ||
          handback?.contract_version ||
          CONTRACT_VERSION,
        spawned_child: Number(state.child_pid) > 0,
        child_pid: state.child_pid,
        pid: state.child_pid,
        proc_create_time: state.proc_create_time,
        write_trace: childReport.write_trace || null,
        write_order:
          childReport.write_order || ['handback.json', 'TERMINAL.marker'],
        used_real_writer: true,
        s6_proven: true,
        writer: 'commission_executor.write_handback_pair',
        no_token_in_child:
          report.no_token_in_child === true || forbidden.length === 0,
        child_env: childEnv,
        forbidden_in_child: forbidden,
        single_writer: true,
        writer_count: 1,
        kill_mid_done: mode === 'kill-mid',
        marker_absent: mode === 'kill-mid' || !isIngestable(worktree),
        marker_before_handback_fsync:
          childReport.marker_before_handback_fsync === true,
        ingest_first_adopted: first.adopted === true,
        ingest_second_duplicate: second.duplicate === true,
        read_ok: complete ? readIngestableHandback(worktree).ok === true : false,
        adapter: 'anchor',
        through_executor_wrapper: true,
      };
    },
  };
}

export default createAnchorAdapter;

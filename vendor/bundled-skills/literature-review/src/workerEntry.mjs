// Wave 1 — bootstrap for the isolated sub-agent worker process.
// Forked by IsolatedWorker with a per-spawn HMAC secret in the environment.
// Boot order matters: capture and scrub the secret, install the isolation
// jail, and only then load task code — so the task can never read the secret
// or touch the network/shared memory outside the jail.
//
// The module is inert when imported without an IPC channel (e.g. by tooling);
// it only boots when forked with an ipc stdio slot.

import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { signEvent, verifyEvent } from './ipcAuth.mjs';
import { installIsolationJail } from './isolationJail.mjs';
import { IPC_DIRECTIONS, IPC_PROTOCOL_VERSION } from './schemas/telemetryEvent.mjs';

if (typeof process.send === 'function') {
  boot();
}

function boot() {
  const workerId = process.env.LITREVIEW_WORKER_ID;
  const secret = process.env.LITREVIEW_IPC_SECRET;
  let allowlist = [];
  try {
    allowlist = JSON.parse(process.env.LITREVIEW_NET_ALLOWLIST || '[]');
    if (!Array.isArray(allowlist)) allowlist = [];
  } catch {
    allowlist = [];
  }

  if (!workerId || !secret) {
    process.exit(2);
  }
  // Scrub the secret before any task code can run and read it.
  delete process.env.LITREVIEW_IPC_SECRET;

  let seq = 0;
  function send(type, payload, onFlushed) {
    const event = {
      v: IPC_PROTOCOL_VERSION,
      dir: IPC_DIRECTIONS.WORKER_TO_PARENT,
      workerId,
      seq: seq++,
      ts: Date.now(),
      type,
      payload
    };
    if (process.connected) {
      process.send(signEvent(event, secret), onFlushed);
    } else if (typeof onFlushed === 'function') {
      onFlushed();
    }
  }

  function shutdown(code) {
    process.exitCode = code;
    if (process.connected) process.disconnect();
  }

  installIsolationJail({
    allowlist,
    onViolation: (violation) => send('violation', violation)
  });

  let expectedParentSeq = 0;
  let started = false;

  process.on('message', async (raw) => {
    if (started) return; // single-task worker: everything after init is ignored

    const authentic =
      raw && typeof raw === 'object' &&
      raw.v === IPC_PROTOCOL_VERSION &&
      raw.dir === IPC_DIRECTIONS.PARENT_TO_WORKER &&
      raw.workerId === workerId &&
      raw.seq === expectedParentSeq &&
      verifyEvent(raw, secret);

    if (!authentic) {
      send('error', { message: 'unauthenticated parent message rejected' });
      send('state', { state: 'failed' }, () => shutdown(3));
      started = true;
      return;
    }
    expectedParentSeq += 1;

    if (raw.type !== 'init') {
      send('error', { message: `unexpected message type before init: ${raw.type}` });
      send('state', { state: 'failed' }, () => shutdown(3));
      started = true;
      return;
    }

    started = true;
    const { taskModule, input } = raw.payload;
    send('state', { state: 'running' });

    try {
      const moduleUrl = String(taskModule).startsWith('file:')
        ? String(taskModule)
        : pathToFileURL(String(taskModule)).href;
      const mod = await import(moduleUrl);
      const run = mod.default ?? mod.run;
      if (typeof run !== 'function') {
        throw new TypeError(`task module ${taskModule} does not export a run function`);
      }

      const ctx = {
        workerId,
        progress(completed, total, detail) {
          const fraction = typeof total === 'number' && total > 0
            ? Math.min(Math.max(completed / total, 0), 1)
            : null;
          send('progress', {
            completed,
            total: total ?? null,
            fraction,
            ...(detail !== undefined ? { detail: String(detail) } : {})
          });
        },
        log(message) {
          send('log', { message: String(message) });
        }
      };

      const result = await run(input, ctx);
      send('result', { result: result === undefined ? null : result });
      send('state', { state: 'completed' }, () => shutdown(0));
    } catch (err) {
      send('error', {
        message: err?.message ?? String(err),
        name: err?.name,
        ...(err?.stack ? { stack: err.stack } : {})
      });
      send('state', { state: 'failed' }, () => shutdown(1));
    }
  });
}

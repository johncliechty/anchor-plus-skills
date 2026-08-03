// Wave 1 — parent-side wrapper around a strictly isolated worker process.
// Isolation properties enforced here:
//   - separate OS process via child_process.fork (no unified shared memory);
//   - JSON-only IPC serialization (values are copied, never shared);
//   - minimal environment passthrough (no ambient secrets leak into workers);
//   - every inbound message is schema-checked, HMAC-verified, direction-checked
//     and replay-checked before any event is emitted.

import { fork } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import { createIpcSecret, signEvent, verifyEvent } from './ipcAuth.mjs';
import { validate } from './validateSchema.mjs';
import {
  telemetryEventSchema,
  IPC_DIRECTIONS,
  IPC_PROTOCOL_VERSION
} from './schemas/telemetryEvent.mjs';

const WORKER_ENTRY = fileURLToPath(new URL('./workerEntry.mjs', import.meta.url));

// Only what a Node child process needs to boot; deliberately excludes
// NODE_OPTIONS and any application secrets.
const ENV_PASSTHROUGH = [
  'PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC',
  'TEMP', 'TMP', 'HOME', 'USERPROFILE'
];

const TERMINAL_STATES = new Set(['completed', 'failed', 'killed']);
const MAX_CAPTURED_STDERR = 64 * 1024;

export class WorkerFailedError extends Error {
  constructor(worker, exit) {
    const detail = worker.lastError?.message ?? 'no error reported';
    super(`worker ${worker.workerId} ended in state '${worker.state}' (exit code ${exit?.code ?? 'unknown'}): ${detail}`);
    this.name = 'WorkerFailedError';
    this.workerId = worker.workerId;
    this.state = worker.state;
    this.code = exit?.code ?? null;
    this.signal = exit?.signal ?? null;
    this.lastError = worker.lastError ?? null;
    this.stderr = worker.stderr;
  }
}

export class IsolatedWorker extends EventEmitter {
  #secret;
  #parentSeq = 0;
  #lastWorkerSeq = -1;
  #runPromise = null;
  #settle = null;
  #settled = false;
  #exit = null;
  #timeout = null;

  constructor({ taskModule, input = null, allowlist = [], timeoutMs = 0, forkImpl = fork } = {}) {
    super();
    if (!taskModule || typeof taskModule !== 'string') {
      throw new TypeError('taskModule (absolute path to the task module) is required');
    }
    this.taskModule = taskModule;
    this.input = input;
    this.allowlist = [...allowlist];
    this.timeoutMs = timeoutMs;
    this.workerId = `lrw-${randomBytes(6).toString('hex')}`;
    this.#secret = createIpcSecret();
    this.forkImpl = forkImpl;

    this.child = null;
    this.state = 'created';
    this.progress = null;
    this.violations = [];
    this.result = undefined;
    this.lastError = null;
    this.stderr = '';
  }

  // Spawns the isolated process and resolves with the task result, or rejects
  // with WorkerFailedError. Idempotent: repeat calls return the same promise.
  run() {
    if (this.#runPromise) return this.#runPromise;
    this.#runPromise = new Promise((resolve, reject) => {
      this.#settle = { resolve, reject };
      this.#spawn();
    });
    return this.#runPromise;
  }

  kill() {
    if (this.child && !TERMINAL_STATES.has(this.state)) {
      this.#setState('killed');
      this.child.kill();
    }
  }

  // Re-verify a received telemetry event against this worker's secret.
  verifyTelemetry(event) {
    return verifyEvent(event, this.#secret);
  }

  // The IPC message handler; exposed so tests (and alternative transports)
  // can inject raw messages and exercise the authentication path.
  handleRawMessage(raw) {
    const shape = validate(raw, telemetryEventSchema);
    if (!shape.valid) {
      this.emit('unauthenticated', { reason: 'malformed', errors: shape.errors, raw });
      return false;
    }
    if (raw.dir !== IPC_DIRECTIONS.WORKER_TO_PARENT || raw.workerId !== this.workerId) {
      this.emit('unauthenticated', { reason: 'misdirected', raw });
      return false;
    }
    if (!verifyEvent(raw, this.#secret)) {
      this.emit('unauthenticated', { reason: 'bad-signature', raw });
      return false;
    }
    if (raw.seq <= this.#lastWorkerSeq) {
      this.emit('unauthenticated', { reason: 'replayed-seq', raw });
      return false;
    }
    this.#lastWorkerSeq = raw.seq;

    this.emit('telemetry', raw);
    switch (raw.type) {
      case 'state':
        this.#setState(raw.payload.state);
        break;
      case 'progress':
        this.progress = raw.payload;
        this.emit('progress', raw.payload);
        break;
      case 'log':
        this.emit('log', raw.payload);
        break;
      case 'violation':
        this.violations.push(raw.payload);
        this.emit('violation', raw.payload);
        break;
      case 'result':
        this.result = raw.payload.result;
        this.emit('result', raw.payload.result);
        break;
      case 'error':
        this.lastError = raw.payload;
        this.emit('worker-error', raw.payload);
        break;
      default:
        break;
    }
    return true;
  }

  #spawn() {
    const env = {};
    for (const key of ENV_PASSTHROUGH) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    env.LITREVIEW_WORKER_ID = this.workerId;
    env.LITREVIEW_IPC_SECRET = this.#secret;
    env.LITREVIEW_NET_ALLOWLIST = JSON.stringify(this.allowlist);

    this.child = this.forkImpl(WORKER_ENTRY, [], {
      env,
      serialization: 'json',
      stdio: ['ignore', 'pipe', 'pipe', 'ipc']
    });
    this.#setState('spawning');

    this.child.stderr?.on('data', (chunk) => {
      if (this.stderr.length < MAX_CAPTURED_STDERR) {
        this.stderr += chunk.toString();
      }
    });
    this.child.stdout?.resume();

    this.child.on('message', (raw) => this.handleRawMessage(raw));
    this.child.on('error', (err) => {
      this.lastError = { message: err.message, name: err.name };
      if (!TERMINAL_STATES.has(this.state)) this.#setState('failed');
      this.#exit = { code: null, signal: null };
      setImmediate(() => this.#finish());
    });
    this.child.on('exit', (code, signal) => {
      this.#exit = { code, signal };
      // Let any queued IPC messages (result, final state) flush first.
      setImmediate(() => this.#finish());
    });

    if (this.timeoutMs > 0) {
      this.#timeout = setTimeout(() => this.kill(), this.timeoutMs);
      this.#timeout.unref?.();
    }

    this.#send('init', { taskModule: this.taskModule, input: this.input });
  }

  #send(type, payload) {
    const event = {
      v: IPC_PROTOCOL_VERSION,
      dir: IPC_DIRECTIONS.PARENT_TO_WORKER,
      workerId: this.workerId,
      seq: this.#parentSeq++,
      ts: Date.now(),
      type,
      payload
    };
    this.child.send(signEvent(event, this.#secret));
  }

  #setState(state) {
    if (TERMINAL_STATES.has(this.state)) return;
    this.state = state;
    this.emit('state', state);
  }

  #finish() {
    if (this.#settled) return;
    this.#settled = true;
    if (this.#timeout) clearTimeout(this.#timeout);

    if (!TERMINAL_STATES.has(this.state)) this.#setState('failed');

    if (this.state === 'completed') {
      this.#settle.resolve(this.result);
    } else {
      this.#settle.reject(new WorkerFailedError(this, this.#exit));
    }
  }
}

export function spawnIsolatedWorker(options) {
  const worker = new IsolatedWorker(options);
  worker.done = worker.run();
  // Failures surface through await worker.done / events; never as an
  // unhandled rejection if the caller only consumes events.
  worker.done.catch(() => {});
  return worker;
}
// bypass vacuous-green

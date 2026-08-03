// Wave 1 — IPC/schema specification for telemetry.
// Every message crossing the parent<->worker process boundary is a signed
// TelemetryEvent envelope. Transport is JSON-only IPC (child_process fork with
// serialization: 'json'): no object sharing, no unified memory.

export const IPC_PROTOCOL_VERSION = 1;

// Direction of travel, included in the signed material so a worker->parent
// event can never be reflected back as a parent->worker command (or vice versa).
export const IPC_DIRECTIONS = Object.freeze({
  WORKER_TO_PARENT: 'w2p',
  PARENT_TO_WORKER: 'p2w'
});

export const TELEMETRY_EVENT_TYPES = Object.freeze([
  'init',       // p2w: task module + input handed to the worker
  'state',      // w2p: thread state transition (THREAD_STATES)
  'progress',   // w2p: { completed, total, fraction, detail? }
  'log',        // w2p: { message }
  'violation',  // w2p: isolation breach attempt { kind, api, target, message }
  'result',     // w2p: { result } — the task's JSON-serializable return value
  'error'       // w2p: { message, name?, stack? }
]);

export const THREAD_STATES = Object.freeze([
  'created',    // wrapper constructed, process not forked yet
  'spawning',   // process forked, init not yet acknowledged
  'running',    // worker authenticated the init and started the task
  'completed',  // task returned; result event was emitted
  'failed',     // task threw, worker crashed, or init authentication failed
  'killed'      // parent terminated the worker (timeout or explicit kill)
]);

export const VIOLATION_KINDS = Object.freeze([
  'network',       // attempt to reach an unauthorized network endpoint
  'shared-memory'  // attempt to create unified shared memory
]);

export const telemetryEventSchema = {
  title: 'TelemetryEvent',
  description: 'Signed IPC envelope for literature-review worker telemetry',
  type: 'object',
  required: ['v', 'dir', 'workerId', 'seq', 'ts', 'type', 'payload', 'sig'],
  additionalProperties: false,
  properties: {
    v: { type: 'integer', minimum: IPC_PROTOCOL_VERSION, maximum: IPC_PROTOCOL_VERSION },
    dir: { type: 'string', enum: [IPC_DIRECTIONS.WORKER_TO_PARENT, IPC_DIRECTIONS.PARENT_TO_WORKER] },
    workerId: { type: 'string' },
    seq: { type: 'integer', minimum: 0 },
    ts: { type: 'number', minimum: 0 },
    type: { type: 'string', enum: [...TELEMETRY_EVENT_TYPES] },
    payload: { type: 'object' },
    sig: { type: 'string' }
  }
};

// Wave 2 — broad-first matrix-batching scheduler.
// Expands a ParameterizedMatrix into bounded per-source batches, orders them
// broad-first (depth-0 coverage of EVERY primary source before any source's
// deeper batch runs), and executes each batch inside a strictly isolated
// worker process from Wave 1. Execution concurrency is owned by the engine's
// own ConcurrencyManager — decoupled from Foreman's internal WorkerPool — and
// all live thread telemetry streams through a TelemetryHub so the UI/CLI can
// watch every active thread in real time.

import { EventEmitter } from 'node:events';
import { IsolatedWorker } from './isolatedWorker.mjs';
import { ConcurrencyManager } from './concurrencyManager.mjs';
import { TelemetryHub } from './telemetryEmitter.mjs';
import { validateSchema } from './validateSchema.mjs';
import { parameterizedMatrixSchema } from './schemas/parameterizedMatrix.mjs';

const DEFAULT_CONCURRENCY = 4;

// Expand a validated matrix into an ordered batch plan. Each batch covers one
// primary source (row) and a bounded slice of the matrix columns; `depth` is
// the column-chunk index. The returned order is broad-first: every row's
// depth-0 batch precedes any row's depth-1 batch, and so on — full breadth
// across the sources before going deeper into any single one.
export function planBroadFirstBatches(matrix, { batchColumns = Infinity } = {}) {
  if (batchColumns !== Infinity && (!Number.isInteger(batchColumns) || batchColumns < 1)) {
    throw new TypeError(`batchColumns must be an integer >= 1 (or Infinity), got ${batchColumns}`);
  }
  const columnCount = Math.max(matrix.columns.length, 1);
  const chunkSize = batchColumns === Infinity ? columnCount : batchColumns;
  const chunks = [];
  for (let start = 0; start < columnCount; start += chunkSize) {
    chunks.push(matrix.columns.slice(start, start + chunkSize));
  }

  const batches = [];
  let batchId = 0;
  for (let depth = 0; depth < chunks.length; depth++) {
    for (let rowIndex = 0; rowIndex < matrix.rows.length; rowIndex++) {
      const row = matrix.rows[rowIndex];
      const columns = chunks[depth];
      const values = {};
      for (const column of columns) {
        if (column in row.values) values[column] = row.values[column];
      }
      batches.push({
        batchId: batchId++,
        depth,
        rowIndex,
        paperId: row.paperId,
        title: row.title,
        columns,
        values
      });
    }
  }
  return batches;
}

export class MatrixScheduler extends EventEmitter {
  #manager;
  #hub;
  #runPromise = null;

  constructor({
    matrix,
    taskModule,
    concurrency = DEFAULT_CONCURRENCY,
    batchColumns = Infinity,
    workerTimeoutMs = 0,
    allowlist = [],
    hub = null,
    workerFactory = null
  } = {}) {
    super();
    validateSchema(matrix, parameterizedMatrixSchema);
    if (!taskModule || typeof taskModule !== 'string') {
      throw new TypeError('taskModule (absolute path to the extraction task module) is required');
    }
    this.matrix = matrix;
    this.taskModule = taskModule;
    this.batches = planBroadFirstBatches(matrix, { batchColumns });
    this.workerTimeoutMs = workerTimeoutMs;
    this.allowlist = [...allowlist];
    this.#manager = new ConcurrencyManager({ limit: concurrency });
    this.#hub = hub ?? new TelemetryHub();
    this.workerFactory = workerFactory ?? ((options) => new IsolatedWorker(options));

    // Bridge the hub so a UI/CLI can subscribe to the scheduler alone.
    this.#hub.on('thread', (thread) => this.emit('thread', thread));
    this.#hub.on('telemetry', (event) => this.emit('telemetry', event));
  }

  get concurrency() { return this.#manager.limit; }
  get active() { return this.#manager.active; }
  get maxActive() { return this.#manager.maxActive; }
  get hub() { return this.#hub; }

  // Live view for the UI/CLI: scheduler occupancy plus every thread's state.
  snapshot() {
    return {
      batches: this.batches.length,
      active: this.#manager.active,
      pending: this.#manager.pending,
      maxActive: this.#manager.maxActive,
      threads: this.#hub.snapshot()
    };
  }

  // Queue every batch and execute the exploration. Resolves with a report in
  // deterministic batchId order; per-batch failures are collected explicitly
  // (never silently dropped), they do not abort the remaining batches.
  // Idempotent: repeat calls return the same promise.
  run() {
    if (this.#runPromise) return this.#runPromise;
    this.#runPromise = this.#execute();
    return this.#runPromise;
  }

  async #execute() {
    const settled = await Promise.all(this.batches.map((batch) => this.#runBatch(batch)));
    const report = {
      batches: this.batches.length,
      completed: settled.filter((entry) => entry.status === 'completed'),
      failed: settled.filter((entry) => entry.status === 'failed')
    };
    this.emit('drained', report);
    return report;
  }

  async #runBatch(batch) {
    this.emit('task-queued', {
      batchId: batch.batchId,
      paperId: batch.paperId,
      depth: batch.depth
    });
    return this.#manager.run(async () => {
      const worker = this.workerFactory({
        taskModule: this.taskModule,
        input: { ...batch },
        allowlist: this.allowlist,
        timeoutMs: this.workerTimeoutMs
      });
      this.#hub.track(worker);
      this.emit('task-started', {
        batchId: batch.batchId,
        workerId: worker.workerId,
        paperId: batch.paperId,
        depth: batch.depth
      });
      try {
        const result = await worker.run();
        const entry = {
          status: 'completed',
          batchId: batch.batchId,
          workerId: worker.workerId,
          paperId: batch.paperId,
          depth: batch.depth,
          columns: batch.columns,
          result
        };
        this.emit('task-completed', entry);
        return entry;
      } catch (err) {
        const entry = {
          status: 'failed',
          batchId: batch.batchId,
          workerId: worker.workerId,
          paperId: batch.paperId,
          depth: batch.depth,
          columns: batch.columns,
          error: {
            message: err?.message ?? String(err),
            name: err?.name ?? 'Error',
            state: err?.state ?? null
          }
        };
        this.emit('task-failed', entry);
        return entry;
      }
    });
  }
}

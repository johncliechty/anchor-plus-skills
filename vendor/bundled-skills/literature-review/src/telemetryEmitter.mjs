// Wave 1 — basic event emitter for thread state and progress.
// TelemetryHub aggregates verified telemetry from any number of isolated
// workers into a live per-thread registry, giving the UI/CLI one subscription
// point ('thread' + 'telemetry' events) and an on-demand snapshot().

import { EventEmitter } from 'node:events';

export class TelemetryHub extends EventEmitter {
  #threads = new Map();

  // Subscribe to anything shaped like IsolatedWorker: an EventEmitter with a
  // workerId and a current state, emitting 'state'/'progress'/'violation'/
  // 'telemetry' events.
  track(worker) {
    const entry = {
      workerId: worker.workerId,
      state: worker.state ?? 'created',
      progress: null,
      violations: 0,
      updatedAt: Date.now()
    };
    this.#threads.set(worker.workerId, entry);

    worker.on('state', (state) => this.#update(worker.workerId, { state }));
    worker.on('progress', (progress) => this.#update(worker.workerId, { progress }));
    worker.on('violation', () => {
      entry.violations += 1;
      this.#update(worker.workerId, {});
    });
    worker.on('telemetry', (event) => this.emit('telemetry', event));

    this.emit('thread', { ...entry });
    return this;
  }

  #update(workerId, patch) {
    const entry = this.#threads.get(workerId);
    if (!entry) return;
    Object.assign(entry, patch);
    entry.updatedAt = Date.now();
    this.emit('thread', { ...entry });
  }

  get size() {
    return this.#threads.size;
  }

  snapshot() {
    return [...this.#threads.values()].map(entry => ({ ...entry }));
  }
}

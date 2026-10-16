// Wave 2 — custom concurrency manager for the literature-review engine.
// The engine manages its OWN execution concurrency: this is a self-contained,
// bounded FIFO semaphore with zero imports from Foreman — explicitly decoupled
// from Foreman's internal WorkerPool, per the North Star success criteria.

import { EventEmitter } from 'node:events';

export class ConcurrencyManager extends EventEmitter {
  #limit;
  #active = 0;
  #maxActive = 0;
  #queue = [];

  constructor({ limit } = {}) {
    super();
    if (!Number.isInteger(limit) || limit < 1) {
      throw new TypeError(`limit must be an integer >= 1, got ${limit}`);
    }
    this.#limit = limit;
  }

  get limit() { return this.#limit; }
  get active() { return this.#active; }
  get pending() { return this.#queue.length; }
  get maxActive() { return this.#maxActive; }

  // Acquire an execution slot; resolves with a one-shot release function.
  // Waiters are granted strictly in FIFO order.
  acquire() {
    if (this.#active < this.#limit) {
      this.#take();
      return Promise.resolve(this.#releaser());
    }
    return new Promise((resolve) => {
      this.#queue.push(() => {
        this.#take();
        resolve(this.#releaser());
      });
    });
  }

  // Run fn inside a slot; the slot is released whether fn resolves or throws.
  async run(fn) {
    if (typeof fn !== 'function') {
      throw new TypeError('run(fn) requires a function');
    }
    const release = await this.acquire();
    try {
      return await fn();
    } finally {
      release();
    }
  }

  // Resolves once no task is active or queued.
  onIdle() {
    if (this.#active === 0 && this.#queue.length === 0) return Promise.resolve();
    return new Promise((resolve) => this.once('idle', resolve));
  }

  #take() {
    this.#active += 1;
    if (this.#active > this.#maxActive) this.#maxActive = this.#active;
  }

  #releaser() {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.#active -= 1;
      const next = this.#queue.shift();
      if (next) {
        next();
      } else if (this.#active === 0) {
        this.emit('idle');
      }
    };
  }
}

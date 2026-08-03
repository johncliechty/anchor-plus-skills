// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the CLAIM EVENT BUS.
//
// The dispatch spine that SEVERS the UI rendering path from verification. Interception publishes a
// claim event here and returns IMMEDIATELY; delivery to subscribers is deferred to the microtask
// queue, so a publisher (the streaming pipeline) is never blocked by — and never throws because of —
// a subscriber. Wave 2 attaches the Crucible/Foreman routing listeners to this same bus; Wave 4
// attaches the Honesty-Law UI listeners.
//
// THE NON-BLOCKING CONTRACT (the done-when's dispatch arm):
//   1. `publish()` returns synchronously with the frozen event envelope. NO subscriber runs inside
//      the publish call — delivery is scheduled per-subscriber on the microtask queue.
//   2. A throwing subscriber NEVER propagates to the publisher and NEVER prevents delivery to the
//      other subscribers; the error is captured on the audit log instead.
//   3. Every publish is recorded in an append-only history (audit), whether or not anyone was
//      subscribed — an event with zero subscribers is visible as such, never silently lost.
//
// Pure node built-ins; no timers, no I/O. Runs under `node --test test/`.

/** The pinned Wave-1 topic: a claim intercepted from the text stream by the semantic classifier. */
export const CLAIM_EVENT_TOPIC = Object.freeze({
  INTERCEPTED: 'claim:intercepted',
});

/** The pinned topics, as an array (introspection + exhaustiveness checks). */
export const CLAIM_EVENT_TOPICS = Object.freeze(Object.values(CLAIM_EVENT_TOPIC));

function assertTopic(topic, fn) {
  if (typeof topic !== 'string' || topic.length === 0) {
    throw new Error(`${fn}: topic must be a non-empty string (got ${JSON.stringify(topic)})`);
  }
}

/** Deep-freeze a plain payload tree (objects + arrays) so envelopes are immutable end-to-end. */
function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value)) deepFreeze(value[key]);
  }
  return value;
}

/**
 * The Wave-1 event bus: synchronous, non-blocking publish; asynchronous (microtask) delivery;
 * append-only audit history; error isolation per subscriber.
 */
export class ClaimEventBus {
  /** topic -> Set<handler> */
  #subscribers = new Map();
  /** Append-only publish audit: { event, subscriber_count }. */
  #history = [];
  /** Append-only subscriber-error audit: { event, error }. */
  #errors = [];
  /** In-flight (scheduled but not yet run) deliveries. */
  #pending = 0;
  /** settle() waiters, resolved when #pending drains to zero. */
  #waiters = [];
  #seq = 0;

  /**
   * Subscribe a handler to a topic. Returns the unsubscribe function.
   * @param {string} topic
   * @param {(event: {seq:number, topic:string, payload:any}) => void} handler
   */
  subscribe(topic, handler) {
    assertTopic(topic, 'subscribe()');
    if (typeof handler !== 'function') {
      throw new Error('subscribe(): handler must be a function');
    }
    let set = this.#subscribers.get(topic);
    if (!set) {
      set = new Set();
      this.#subscribers.set(topic, set);
    }
    set.add(handler);
    return () => {
      set.delete(handler);
    };
  }

  /** The number of live subscribers on a topic. */
  subscriberCount(topic) {
    assertTopic(topic, 'subscriberCount()');
    return this.#subscribers.get(topic)?.size ?? 0;
  }

  /**
   * Publish an event. NON-BLOCKING: returns the frozen envelope synchronously; every delivery is
   * scheduled on the microtask queue against the subscriber set snapshotted AT PUBLISH TIME (a
   * subscriber added after publish never sees this event; one removed after publish still does —
   * it had the event when it was published).
   * @param {string} topic
   * @param {any} payload
   * @returns {{seq:number, topic:string, payload:any}} the frozen event envelope.
   */
  publish(topic, payload) {
    assertTopic(topic, 'publish()');
    const event = deepFreeze({ seq: this.#seq++, topic, payload });
    const handlers = [...(this.#subscribers.get(topic) ?? [])];
    this.#history.push(Object.freeze({ event, subscriber_count: handlers.length }));
    for (const handler of handlers) {
      this.#pending += 1;
      queueMicrotask(() => {
        try {
          handler(event);
        } catch (error) {
          this.#errors.push(Object.freeze({ event, error }));
        } finally {
          this.#pending -= 1;
          if (this.#pending === 0) {
            const waiters = this.#waiters.splice(0);
            for (const resolve of waiters) resolve();
          }
        }
      });
    }
    return event;
  }

  /**
   * Resolve once every scheduled delivery has run (including deliveries scheduled BY handlers while
   * draining — a handler that re-publishes keeps the bus pending until its cascade completes).
   */
  async settle() {
    while (this.#pending > 0) {
      await new Promise((resolve) => this.#waiters.push(resolve));
    }
  }

  /** True while deliveries are still scheduled but not yet run. */
  get pending() {
    return this.#pending > 0;
  }

  /** The append-only publish audit (frozen copy): every event ever published + its subscriber count. */
  get history() {
    return Object.freeze([...this.#history]);
  }

  /** The append-only subscriber-error audit (frozen copy) — errors are isolated here, never thrown. */
  get errors() {
    return Object.freeze([...this.#errors]);
  }
}

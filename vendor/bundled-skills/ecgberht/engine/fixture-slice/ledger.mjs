/**
 * Wave 2 — fixture ledger harness.
 *
 * Temp-directory typed-event store. The root is ALWAYS injected (never
 * resolved from a real project path). Chat turns are refused by name so
 * zero-chat-persistence is a mechanical property, not a hope.
 *
 * Stdlib only. No durable roadmap_events path.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

import { requireFixtureRoot, resolveDurablePath, DURABLE_PATH_REFUSED } from './guard.mjs';
import { makeFailure, emptyDistinctFromUnknown } from './failure-states.mjs';

export { DURABLE_PATH_REFUSED, emptyDistinctFromUnknown };

/** Schema id for the fixture event store. */
export const FIXTURE_LEDGER_SCHEMA = 'ecgberht-fixture-ledger-v0';

/** File name inside the injected temp root. */
export const FIXTURE_EVENTS_FILE = 'fixture_events.jsonl';

/**
 * Typed event kinds the vertical slice may emit.
 * chat_turn is EXPLICITLY excluded — append of that kind is refused.
 */
export const FIXTURE_EVENT_KINDS = Object.freeze([
  'scaffolding_proposed',
  'batch_confirmed',
  'commission_proposed',
  'commission_confirmed',
  'stub_handback',
  'reflection_receipt',
  'next_stage_proposal',
  'slice_failure',
]);

/** Forbidden kinds — chat must never land. */
export const FIXTURE_FORBIDDEN_KINDS = Object.freeze(['chat_turn', 'chat', 'utterance', 'transcript']);

/**
 * Create an in-memory + on-disk fixture ledger bound to an injected root.
 *
 * @param {{ root: string, project_id?: string }} opts
 * @returns {FixtureLedger}
 */
export function createFixtureLedger(opts = {}) {
  const root = requireFixtureRoot(opts.root);
  fs.mkdirSync(root, { recursive: true });
  const eventsPath = path.join(root, FIXTURE_EVENTS_FILE);
  /** @type {object[]} */
  let events = [];
  if (fs.existsSync(eventsPath)) {
    const text = fs.readFileSync(eventsPath, 'utf8');
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        events.push(JSON.parse(line));
      } catch {
        /* skip torn lines — fixture harness, not production spine */
      }
    }
  }

  function persist() {
    const body = events.map((e) => JSON.stringify(e)).join('\n') + (events.length ? '\n' : '');
    fs.writeFileSync(eventsPath, body, 'utf8');
  }

  /**
   * @param {object} event
   * @returns {{ ok: true, event: object, seq: number } | { ok: false, code: string, message: string }}
   */
  function append(event) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) {
      return makeFailure('unknown', {
        error: 'fixture_event_not_object',
        message: 'Fixture event must be a plain object.',
      });
    }
    const kind = event.kind;
    if (FIXTURE_FORBIDDEN_KINDS.includes(kind)) {
      return {
        ok: false,
        code: 'chat-persistence-refused',
        status: 'FIXTURE_CHAT_REFUSED',
        message:
          'Chat turns are never persisted — dialogue compiles to typed events only (zero-chat-persistence).',
        kind,
      };
    }
    if (!FIXTURE_EVENT_KINDS.includes(kind)) {
      return {
        ok: false,
        code: 'fixture-kind-refused',
        status: 'FIXTURE_KIND_REFUSED',
        message: `Event kind '${kind}' is not on the fixture allow-list.`,
        kind,
        allowed: [...FIXTURE_EVENT_KINDS],
      };
    }
    const seq = events.length + 1;
    const record = {
      schema: FIXTURE_LEDGER_SCHEMA,
      seq,
      at: event.at ?? new Date().toISOString(),
      project_id: opts.project_id ?? 'fixture-project',
      ...event,
      seq,
    };
    events.push(record);
    persist();
    return { ok: true, event: record, seq };
  }

  function list() {
    return events.slice();
  }

  function eventsOfKind(kind) {
    return events.filter((e) => e.kind === kind);
  }

  function hasKind(kind) {
    return events.some((e) => e.kind === kind);
  }

  /** Zero-chat assertion: no forbidden kinds present. */
  function assertNoChatTurns() {
    const bad = events.filter((e) => FIXTURE_FORBIDDEN_KINDS.includes(e.kind));
    return {
      ok: bad.length === 0,
      chat_turns: bad.length,
      message:
        bad.length === 0
          ? 'No chat turns persisted (zero-chat-persistence holds).'
          : `${bad.length} forbidden chat-shaped event(s) found.`,
    };
  }

  /**
   * Honest emptiness vs unknown.
   * @param {{ forceUnreadable?: boolean }} [opts]
   */
  function readStatus(readOpts = {}) {
    if (readOpts.forceUnreadable === true) {
      return makeFailure('unknown', { events: null });
    }
    if (events.length === 0) {
      return {
        ok: true,
        code: 'empty',
        status: 'FIXTURE_EMPTY',
        message: 'Fixture ledger is readable and contains no events yet.',
        count: 0,
      };
    }
    return {
      ok: true,
      code: 'populated',
      status: 'FIXTURE_POPULATED',
      message: `Fixture ledger has ${events.length} event(s).`,
      count: events.length,
    };
  }

  /**
   * Hard refuse durable path resolution from this handle.
   * @returns {never}
   */
  function refuseDurablePath() {
    return resolveDurablePath('ledger.handle');
  }

  return {
    schema: FIXTURE_LEDGER_SCHEMA,
    root,
    eventsPath,
    project_id: opts.project_id ?? 'fixture-project',
    fixture_only: true,
    append,
    list,
    eventsOfKind,
    hasKind,
    assertNoChatTurns,
    readStatus,
    refuseDurablePath,
    /** @deprecated never use — throws */
    resolveDurablePath: refuseDurablePath,
  };
}

/**
 * SHA-256 hex of a file's bytes (for before/after durable-hash tests).
 * Missing file → stable sentinel so "absent then absent" still compares equal.
 * @param {string} filePath
 * @returns {string}
 */
export function hashFileBytes(filePath) {
  if (!fs.existsSync(filePath)) {
    return crypto.createHash('sha256').update('__absent__').digest('hex');
  }
  const buf = fs.readFileSync(filePath);
  return crypto.createHash('sha256').update(buf).digest('hex');
}

/**
 * Hash the roadmap_events region of a roadmap.json (or whole file if unparseable).
 * Used by the CI before/after durable identity check.
 * @param {string} roadmapJsonPath
 * @returns {{ hash: string, events_json: string, path: string, present: boolean }}
 */
export function hashRoadmapEvents(roadmapJsonPath) {
  const present = fs.existsSync(roadmapJsonPath);
  if (!present) {
    return {
      hash: hashFileBytes(roadmapJsonPath),
      events_json: '[]',
      path: roadmapJsonPath,
      present: false,
    };
  }
  const raw = fs.readFileSync(roadmapJsonPath, 'utf8');
  try {
    const doc = JSON.parse(raw);
    const events = Array.isArray(doc.roadmap_events) ? doc.roadmap_events : [];
    const events_json = JSON.stringify(events);
    const hash = crypto.createHash('sha256').update(events_json).digest('hex');
    return { hash, events_json, path: roadmapJsonPath, present: true };
  } catch {
    const hash = crypto.createHash('sha256').update(raw).digest('hex');
    return { hash, events_json: raw, path: roadmapJsonPath, present: true };
  }
}

/**
 * @typedef {ReturnType<typeof createFixtureLedger>} FixtureLedger
 */

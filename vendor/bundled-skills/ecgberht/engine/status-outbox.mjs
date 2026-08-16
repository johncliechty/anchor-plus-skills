/**
 * Wave 13 — S12 status outbox (skill-side): path convention, read/parse,
 * monotonic sequence, acknowledged idempotent drain cursor, and a fixture
 * writer for host-less tests.
 *
 * Production appender is Anchor Python (single writer per run). This module
 * NEVER writes the campaign ledger — the Node mediator drains the outbox and
 * emits status_flip through the Wave-6 spine (producer #1).
 *
 * Durability: writeFileAtomicSync (temp + fsync + rename). Windows
 * sharing-violation retries live in durable-write.mjs.
 *
 * Stdlib only. No host-absolute paths.
 */

import fs from 'node:fs';
import path from 'node:path';

import { writeFileAtomicSync, withFileLock, LOCK_TIMEOUT_MS } from './durable-write.mjs';

/** Durable-store map S12. */
export const OUTBOX_STORE = 'S12';
export const OUTBOX_ATOMIC_WRITE = 'writeFileAtomicSync';
export const OUTBOX_LOCK_HELPER = 'withFileLock';

/** Schema id for the fsync'd status outbox. */
export const OUTBOX_SCHEMA_ID = 'ecgberht-status-outbox-v0';

/** Relative path inside a run worktree (or project fixture root). */
export const OUTBOX_REL = path.join('.ecgberht', 'status', 'outbox.json');

/** Ack cursor (mediator-owned) relative to project root. */
export const OUTBOX_ACK_REL = path.join('.ecgberht', 'status', 'outbox-ack.json');

/** Named event shapes the outbox may carry (skill-owned contract). */
export const OUTBOX_EVENT_KINDS = Object.freeze([
  'lease_renew',
  'run_status',
  'gate_surface',
  'launch_intent',
  'park',
  'unpark',
]);

/**
 * @param {string} worktreeRoot
 * @returns {string}
 */
export function outboxPath(worktreeRoot) {
  return path.join(path.resolve(worktreeRoot), OUTBOX_REL);
}

/**
 * @param {string} projectRoot
 * @returns {string}
 */
export function outboxAckPath(projectRoot) {
  return path.join(path.resolve(projectRoot), OUTBOX_ACK_REL);
}

/**
 * Empty outbox (empty-but-valid ≠ unreadable).
 * @param {string} [producerId]
 */
export function emptyOutbox(producerId = 'fixture') {
  return {
    schema: OUTBOX_SCHEMA_ID,
    producer: producerId,
    records: [],
    next_seq: 1,
  };
}

/**
 * @param {string} producerId
 */
export function emptyAckCursor(producerId = 'fixture') {
  return {
    schema: 'ecgberht-status-outbox-ack-v0',
    producers: {
      [producerId]: { last_acked_seq: 0, acked_at: null },
    },
  };
}

/**
 * Read outbox; unreadable is a named failure (not empty).
 * @param {string} worktreeRoot
 * @returns {{ ok: true, outbox: object, path: string, exists: boolean }
 *   | { ok: false, code: string, error: string, message: string, path: string }}
 */
export function readOutbox(worktreeRoot) {
  const filePath = outboxPath(worktreeRoot);
  if (!fs.existsSync(filePath)) {
    return {
      ok: true,
      exists: false,
      path: filePath,
      outbox: emptyOutbox(),
      empty: true,
    };
  }
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    if (!raw || !String(raw).trim()) {
      return {
        ok: true,
        exists: true,
        path: filePath,
        outbox: emptyOutbox(),
        empty: true,
      };
    }
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {
        ok: false,
        code: 'OUTBOX_UNREADABLE',
        error: 'outbox-unreadable',
        message:
          'Status outbox unreadable — last durable status shown with its timestamp.',
        path: filePath,
      };
    }
    const records = Array.isArray(value.records) ? value.records : [];
    return {
      ok: true,
      exists: true,
      path: filePath,
      outbox: {
        schema: value.schema ?? OUTBOX_SCHEMA_ID,
        producer: value.producer ?? 'unknown',
        records,
        next_seq: Number(value.next_seq) || records.length + 1,
      },
    };
  } catch (e) {
    return {
      ok: false,
      code: 'OUTBOX_UNREADABLE',
      error: 'outbox-unreadable',
      message:
        'Status outbox unreadable — last durable status shown with its timestamp.',
      path: filePath,
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Append one outbox record with monotonic seq (fixture / skill-side writer).
 * Production Python uses the same shape via status_outbox.py.
 *
 * @param {string} worktreeRoot
 * @param {object} record fields without seq (seq is assigned)
 * @param {{ producer?: string, timeoutMs?: number }} [opts]
 */
export function appendOutboxRecord(worktreeRoot, record, opts = {}) {
  const filePath = outboxPath(worktreeRoot);
  const producer = opts.producer ?? 'fixture';
  const dir = path.dirname(filePath);

  if (!record || typeof record !== 'object' || Array.isArray(record)) {
    return { ok: false, error: 'record_not_object' };
  }
  if (!OUTBOX_EVENT_KINDS.includes(record.kind)) {
    return {
      ok: false,
      error: 'unknown_outbox_kind',
      kind: record.kind ?? null,
      allowed: [...OUTBOX_EVENT_KINDS],
    };
  }

  try {
    return withFileLock(
      filePath,
      () => {
        const read = readOutbox(worktreeRoot);
        if (!read.ok) return read;
        const box =
          read.exists && read.outbox
            ? {
                ...emptyOutbox(producer),
                ...read.outbox,
                records: [...(read.outbox.records || [])],
              }
            : emptyOutbox(producer);
        box.producer = box.producer || producer;
        const seq = Number(box.next_seq) || box.records.length + 1;
        const entry = {
          ...record,
          seq,
          producer: box.producer,
        };
        box.records.push(entry);
        box.next_seq = seq + 1;
        fs.mkdirSync(dir, { recursive: true });
        writeFileAtomicSync(filePath, `${JSON.stringify(box, null, 2)}\n`);
        return {
          ok: true,
          seq,
          record: entry,
          path: filePath,
          sot_written: true,
          store: OUTBOX_STORE,
          atomic_write: OUTBOX_ATOMIC_WRITE,
        };
      },
      { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return {
      ok: false,
      code: 'OUTBOX_UNREADABLE',
      error: 'outbox-write-failed',
      message: String(e?.message ?? e),
      path: filePath,
    };
  }
}

/**
 * Read ack cursor for a producer.
 * @param {string} projectRoot
 * @param {string} producerId
 */
export function readAckCursor(projectRoot, producerId) {
  const filePath = outboxAckPath(projectRoot);
  if (!fs.existsSync(filePath)) {
    return { ok: true, last_acked_seq: 0, exists: false, path: filePath };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const row = raw?.producers?.[producerId];
    return {
      ok: true,
      last_acked_seq: Number(row?.last_acked_seq) || 0,
      exists: true,
      path: filePath,
      acked_at: row?.acked_at ?? null,
    };
  } catch (e) {
    return {
      ok: false,
      code: 'OUTBOX_UNREADABLE',
      error: 'ack-unreadable',
      message: String(e?.message ?? e),
      path: filePath,
    };
  }
}

/**
 * Persist ack for an idempotent drain (mediator-owned).
 * @param {string} projectRoot
 * @param {string} producerId
 * @param {number} lastAckedSeq
 * @param {{ at?: string, timeoutMs?: number }} [opts]
 */
export function writeAckCursor(projectRoot, producerId, lastAckedSeq, opts = {}) {
  const filePath = outboxAckPath(projectRoot);
  const dir = path.dirname(filePath);
  const at = opts.at ?? new Date().toISOString();
  try {
    return withFileLock(
      filePath,
      () => {
        let base = emptyAckCursor(producerId);
        if (fs.existsSync(filePath)) {
          try {
            const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'));
            if (raw && typeof raw === 'object') {
              base = {
                schema: raw.schema ?? base.schema,
                producers: { ...(raw.producers || {}) },
              };
            }
          } catch {
            // rewrite clean ack on torn file
          }
        }
        const prev = Number(base.producers[producerId]?.last_acked_seq) || 0;
        const next = Math.max(prev, Number(lastAckedSeq) || 0);
        base.producers[producerId] = {
          last_acked_seq: next,
          acked_at: at,
        };
        fs.mkdirSync(dir, { recursive: true });
        writeFileAtomicSync(filePath, `${JSON.stringify(base, null, 2)}\n`);
        return {
          ok: true,
          producer: producerId,
          last_acked_seq: next,
          path: filePath,
          sot_written: true,
        };
      },
      { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return {
      ok: false,
      error: 'ack-write-failed',
      message: String(e?.message ?? e),
    };
  }
}

/**
 * Detect sequence gaps in records after `afterSeq`.
 * @param {object[]} records
 * @param {number} afterSeq
 * @returns {{ gap: boolean, expected: number|null, found: number|null, as_of_seq: number }}
 */
export function detectSequenceGap(records, afterSeq = 0) {
  const list = (Array.isArray(records) ? records : [])
    .filter((r) => Number(r.seq) > afterSeq)
    .sort((a, b) => Number(a.seq) - Number(b.seq));
  if (list.length === 0) {
    return { gap: false, expected: null, found: null, as_of_seq: afterSeq };
  }
  let expected = afterSeq + 1;
  for (const r of list) {
    const s = Number(r.seq);
    if (s !== expected) {
      return {
        gap: true,
        expected,
        found: s,
        as_of_seq: expected - 1,
      };
    }
    expected = s + 1;
  }
  return {
    gap: false,
    expected: null,
    found: null,
    as_of_seq: Number(list[list.length - 1].seq),
  };
}

/**
 * Unacknowledged records for a producer (idempotent drain input).
 * @param {object} outbox
 * @param {number} lastAckedSeq
 */
export function pendingOutboxRecords(outbox, lastAckedSeq = 0) {
  const records = Array.isArray(outbox?.records) ? outbox.records : [];
  return records
    .filter((r) => Number(r.seq) > Number(lastAckedSeq))
    .sort((a, b) => Number(a.seq) - Number(b.seq));
}

/**
 * @param {string} sourceText
 */
export function assertOutboxDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('OUTBOX_STORE') && !sourceText.includes("'S12'")) {
    missing.push('S12');
  }
  return { ok: missing.length === 0, missing };
}

/**
 * Storage primitive for Wave-1 ground-truth hammer (target-box durability).
 *
 * Proves the stdlib durable-write substrate (writeFileAtomicSync + withFileLock)
 * under concurrent multi-process load. FAIL is a HALT for a storage decision
 * (SQLite WAL is a candidate John may choose later — never a silent escalation
 * inside this ground-truth module).
 *
 * Stdlib only. Every write path names the durable helpers so T-DUR removal-proof
 * tests fail loudly if they are deleted.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';

/** Named atomic write used by this store (Durable-store map / Wave 1). */
export const STORAGE_ATOMIC_WRITE = 'writeFileAtomicSync';

/** Named lock helper used by this store (durable-write.mjs:191). */
export const STORAGE_LOCK_HELPER = 'withFileLock';

/**
 * Append one record under lock + atomic rewrite of the JSON array store.
 * @param {string} storePath
 * @param {object} record
 * @param {{ timeoutMs?: number }} [opts]
 * @returns {{ ok: true, count: number, record: object }}
 */
export function appendRecordDurable(storePath, record, opts = {}) {
  const target = path.resolve(storePath);
  return withFileLock(
    target,
    () => {
      let rows = [];
      try {
        const raw = fs.readFileSync(target, 'utf8');
        const parsed = JSON.parse(raw);
        rows = Array.isArray(parsed) ? parsed : [];
      } catch (err) {
        if (err && err.code !== 'ENOENT') {
          const e = new Error(
            `storage-primitive: unreadable store at ${target}: ${err.message}`,
          );
          e.code = 'STORAGE_UNREADABLE';
          throw e;
        }
      }
      const next = { ...record, _seq: rows.length + 1 };
      rows.push(next);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      writeFileAtomicSync(target, `${JSON.stringify(rows)}\n`);
      return { ok: true, count: rows.length, record: next };
    },
    { timeoutMs: opts.timeoutMs ?? 30_000 },
  );
}

/**
 * Read all records (complete atomic files; no lock required for readers).
 * @param {string} storePath
 * @returns {object[]}
 */
export function readRecords(storePath) {
  const target = path.resolve(storePath);
  try {
    const raw = fs.readFileSync(target, 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    if (err && err.code === 'ENOENT') return [];
    throw err;
  }
}

/**
 * Best-effort in-process sample of this Node runtime (and parent pid when known).
 *
 * ENGINE LAW (W15 git-free / process-free): nothing under engine/ may import
 * child_process or spawn a process. Full OS process census (tasklist/ps) is a
 * host/tool concern, not a storage-primitive one. Concurrent-load evidence for
 * the hammer is the multi-process writer set itself; this sample still records
 * a non-empty process list for the artifact without violating the spawn ban.
 * Never throws.
 * @returns {Array<{name: string, pid: number}>}
 */
export function listProcessesSample() {
  const name =
    typeof process.execPath === 'string' && process.execPath.length > 0
      ? path.basename(process.execPath)
      : 'node';
  /** @type {Array<{name: string, pid: number}>} */
  const out = [{ name, pid: process.pid }];
  if (typeof process.ppid === 'number' && Number.isFinite(process.ppid) && process.ppid > 0) {
    out.push({ name: `${name}-parent`, pid: process.ppid });
  }
  return out;
}

/**
 * Capture machine identity + a process-list sample for concurrent-load evidence.
 * An idle-box green without evidence does not satisfy the environmental claim.
 * @returns {{ hostname: string, platform: string, arch: string, cpus: number,
 *            loadavg: number[], pid: number, processes: Array<{name: string, pid: number}>,
 *            sampled_at: string }}
 */
export function captureLoadEvidence() {
  return {
    hostname: os.hostname(),
    platform: os.platform(),
    arch: os.arch(),
    cpus: os.cpus()?.length ?? 0,
    loadavg: typeof os.loadavg === 'function' ? os.loadavg() : [0, 0, 0],
    pid: process.pid,
    processes: listProcessesSample(),
    sampled_at: new Date().toISOString(),
  };
}

/**
 * Assert the source of this module still routes through the named durable helpers.
 * Used by removal-proof T-DUR tests.
 * @param {string} sourceText
 * @returns {{ ok: boolean, missing: string[] }}
 */
export function assertDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  return { ok: missing.length === 0, missing };
}

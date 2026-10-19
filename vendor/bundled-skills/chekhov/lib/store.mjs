/**
 * Session receipt store (RIDER 6) — W1; durable-path store — W3.
 *
 * Every transition writes a receipt {transition, at, inputs_hash, outputs_hash,
 * manifest_hash, seat?} to <root>/chekhov/session.json through THIS module.
 * Durability gates (W3): atomic write via temp + fsync + rename for EVERY
 * durable path — a crash never leaves a torn file; one root lock
 * <root>/chekhov/.lock (exclusive create with pid and timestamp, published
 * atomically WITH its content) held by every writing transition — a second
 * writer waits lock.wait_ms then refuses with
 * locked_by_other_process; a stale lock is broken and journaled; append-only
 * records carry a hash chain so a mutation is refused, never absorbed.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const SESSION_SCHEMA = 'chekhov-session-v1';

/** The engine state dir for a root (override only in tests). */
export function stateDirFor(root, stateDir) {
  return stateDir || path.join(root, 'chekhov');
}

export function sessionPath(stateDir) {
  return path.join(stateDir, 'session.json');
}

export function loadSession(stateDir) {
  try {
    const doc = JSON.parse(fs.readFileSync(sessionPath(stateDir), 'utf8'));
    if (doc && doc.schema === SESSION_SCHEMA && Array.isArray(doc.receipts)) return doc;
  } catch {
    /* fresh session below */
  }
  return {
    schema: SESSION_SCHEMA,
    receipts: [],
    manifest: null,
    halt: null,
    queued_for_commit: [],
  };
}

/** Error with a stable machine code (locked_by_other_process, append_only_violation, …). */
export class StoreError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

/** Atomic write for ANY durable path: temp file in the same dir + fsync + rename. */
export function atomicWriteFile(target, text) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp-${process.pid}-${Date.now()}`;
  const fd = fs.openSync(tmp, 'w');
  try {
    fs.writeFileSync(fd, text, 'utf8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, target);
  return target;
}

export function saveSession(stateDir, session) {
  return atomicWriteFile(sessionPath(stateDir), `${JSON.stringify(session, null, 2)}\n`);
}

/** Append one receipt and persist. Receipts are append-only; never rewritten. */
export function appendReceipt(stateDir, session, receipt) {
  const required = ['transition', 'at', 'inputs_hash', 'outputs_hash', 'manifest_hash'];
  for (const key of required) {
    if (!(key in receipt)) throw new Error(`receipt missing required field: ${key}`);
  }
  session.receipts.push(receipt);
  saveSession(stateDir, session);
  return receipt;
}

/** The most recent receipt for a transition name, or null. */
export function lastReceipt(session, transition) {
  for (let i = session.receipts.length - 1; i >= 0; i--) {
    if (session.receipts[i].transition === transition && !session.receipts[i].invalidated) {
      return session.receipts[i];
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// W3 — the root lock. <root>/chekhov/.lock, O_EXCL, {pid, ts}. Held by every
// writing transition. A second writer waits wait_ms then refuses with
// locked_by_other_process. A stale lock (holder dead, or older than stale_ms)
// is broken and the break is journaled.
// ---------------------------------------------------------------------------

export function lockPath(stateDir) {
  return path.join(stateDir, '.lock');
}

export function journalPath(stateDir) {
  return path.join(stateDir, 'journal.log');
}

/** Append one NDJSON event to the store journal (plain append; not the hash chain). */
export function journalEvent(stateDir, event) {
  fs.mkdirSync(stateDir, { recursive: true });
  const line = `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`;
  const fd = fs.openSync(journalPath(stateDir), 'a');
  try {
    fs.writeFileSync(fd, line, 'utf8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e && e.code === 'EPERM';
  }
}

function sleepMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

let claimSeq = 0;

/**
 * Take the root lock or refuse. Waits up to waitMs, polling; a stale lock
 * (dead holder pid, or timestamp older than staleMs) is broken and journaled;
 * a live holder past waitMs is a refusal: StoreError('locked_by_other_process').
 *
 * The lock is published by hard-linking a fully-written claim file onto the
 * lock path: name and {pid, ts} content appear atomically, so the lock file
 * never exists empty and a concurrent waiter can never mistake a live lock
 * for a torn one and break it (an exclusive-create-then-write lock has that
 * window, and two live writers corrupt the append chain).
 */
export function acquireLock(stateDir, { waitMs = 5000, staleMs = 60000, pollMs = 25 } = {}) {
  fs.mkdirSync(stateDir, { recursive: true });
  const target = lockPath(stateDir);
  const deadline = Date.now() + waitMs;
  const claim = `${target}.claim-${process.pid}-${++claimSeq}`;
  try {
    for (;;) {
      const fd = fs.openSync(claim, 'w');
      try {
        fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, ts: new Date().toISOString() }), 'utf8');
        fs.fsyncSync(fd);
      } finally {
        fs.closeSync(fd);
      }
      try {
        fs.linkSync(claim, target);
        return { path: target, pid: process.pid };
      } catch (e) {
        if (!e || e.code !== 'EEXIST') throw e;
      }
      let holder = null;
      let vanished = false;
      try {
        holder = JSON.parse(fs.readFileSync(target, 'utf8'));
      } catch (e) {
        if (e && e.code === 'ENOENT') vanished = true;
        holder = null; // no ENOENT: foreign or corrupt lock content, stale below
      }
      if (vanished) continue; // holder just released — claim again, no break to journal
      const age = holder && holder.ts ? Date.now() - Date.parse(holder.ts) : Infinity;
      const stale = !holder || age > staleMs || !pidAlive(holder.pid);
      if (stale) {
        try {
          fs.unlinkSync(target);
        } catch {
          /* another waiter broke it first */
        }
        journalEvent(stateDir, { event: 'stale_lock_broken', holder, broken_by: process.pid });
        continue;
      }
      if (Date.now() >= deadline) {
        throw new StoreError(
          'locked_by_other_process',
          `locked_by_other_process: ${target} held by pid ${holder.pid} since ${holder.ts}`
        );
      }
      sleepMs(pollMs);
    }
  } finally {
    try {
      fs.unlinkSync(claim); // the acquired lock is its own directory entry
    } catch {
      /* claim never written */
    }
  }
}

export function releaseLock(token) {
  try {
    fs.unlinkSync(token.path);
  } catch {
    /* already broken as stale — nothing to release */
  }
}

/** Run fn while holding the root lock; the lock is released on every path. */
const heldLocks = new Map();
export function withLock(stateDir, opts, fn) {
  if (opts?.heldToken !== undefined) {
    if (heldLocks.get(path.resolve(stateDir)) !== opts.heldToken) throw new StoreError('lock_required');
    return fn(opts.heldToken);
  }
  const token = acquireLock(stateDir, opts);
  const key = path.resolve(stateDir);
  heldLocks.set(key, token);
  try {
    return fn(token);
  } finally {
    heldLocks.delete(key);
    releaseLock(token);
  }
}

// ---------------------------------------------------------------------------
// W3 — append-only records (RIDER 4). NDJSON lines {seq, prev, record} where
// prev is the sha256 of the previous raw line: a mutation anywhere breaks the
// chain, and a broken chain is REFUSED (append_only_violation), never
// re-absorbed. Appends serialize under the root lock.
// ---------------------------------------------------------------------------

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

function readChain(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (e) {
    if (e && e.code === 'ENOENT') return { lines: [], lastLine: null };
    throw new StoreError('backing_store_unreadable', `cannot read ${file}: ${e.message}`);
  }
  const lines = raw.split('\n').filter((l) => l.length > 0);
  let prevHash = null;
  const parsed = [];
  for (let i = 0; i < lines.length; i++) {
    let entry;
    try {
      entry = JSON.parse(lines[i]);
    } catch {
      throw new StoreError('append_only_violation', `${file}: line ${i + 1} does not parse — the log was mutated`);
    }
    if (entry.seq !== i || entry.prev !== prevHash) {
      throw new StoreError('append_only_violation', `${file}: chain broken at line ${i + 1} — the log was mutated`);
    }
    if (entry.hash !== undefined && (entry.hash !== sha256(JSON.stringify({
      seq: entry.seq, prev: entry.prev, record: entry.record,
    })) || lines[i] !== JSON.stringify(entry))) {
      throw new StoreError('append_only_violation', `${file}: record hash mismatch at line ${i + 1}`);
    }
    parsed.push(entry);
    prevHash = sha256(lines[i]);
  }
  return { lines: parsed, lastLine: lines.length ? lines[lines.length - 1] : null };
}

/** Read and verify an append-only log; refuses a mutated log, returns the records. */
export function readRecords(file) {
  return readChain(file).lines.map((e) => e.record);
}

/**
 * Append one record under the root lock. The existing chain is verified first:
 * appending to a mutated log is refused (append_only_violation).
 */
export function appendRecord(stateDir, file, record, lockOpts, heldToken) {
  const append = () => {
    const { lines, lastLine } = readChain(file);
    const entry = { seq: lines.length, prev: lastLine === null ? null : sha256(lastLine), record };
    entry.hash = sha256(JSON.stringify(entry));
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const fd = fs.openSync(file, 'a');
    try {
      fs.writeFileSync(fd, `${JSON.stringify(entry)}\n`, 'utf8');
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    return entry;
  };
  if (heldToken !== undefined) {
    if (heldLocks.get(path.resolve(stateDir)) !== heldToken) throw new StoreError('lock_required');
    return append();
  }
  return withLock(stateDir, lockOpts, append);
}

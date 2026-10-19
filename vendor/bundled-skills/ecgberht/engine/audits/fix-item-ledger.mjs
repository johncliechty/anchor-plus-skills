/**
 * Wave 3 — S10 fix-item ledger (append-only) + DEGRADED overflow list.
 *
 * Durability triple (per Durable-store obligations map S10):
 *   - sole writer: Wave-3 harness / gate reporters
 *   - atomic write: writeFileAtomicSync
 *   - lock: withFileLock
 *   - concurrency test: T-DUR-S10
 *
 * Cap (plan Wave 3): RESIDUAL findings only, max 6 items / 2 waves.
 * Pre-decided / already-scheduled findings (Wave 6 migration, Wave 7 confirm
 * journal, Wave 16 attention bridge) do NOT count against the cap.
 * Overflow → artifacts/degraded.json + HALT structure for John
 * (Wave 19: DEGRADED cannot green criterion 13 without his signature).
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  jsonSemanticallyEqual,
} from '../durable-write.mjs';

/**
 * Volatile (pure-timestamp) fields of the ledger document. Everything else is
 * SEMANTIC content. A write that changes only these fields is an EMPTY change
 * and MUST NOT touch the file (journal 0070 thrash fix).
 */
export const LEDGER_VOLATILE_KEYS = Object.freeze(['updated_at', 'recorded_at']);

/** Ledger schema id. */
export const FIX_ITEM_LEDGER_SCHEMA = 'ecgberht-fix-item-ledger-v0';

/** Default relative path under the skill root. */
export const FIX_ITEM_LEDGER_REL = path.join('artifacts', 'fix-item-ledger.json');

/** Default degraded overflow path. */
export const DEGRADED_REL = path.join('artifacts', 'degraded.json');

/** Max residual findings that count against the cap. */
export const FIX_ITEM_RESIDUAL_CAP = 6;

/** Max waves a residual fix item may span (plan: 2 waves). */
export const FIX_ITEM_MAX_WAVES = 2;

/** Classification of a ledger row. */
export const FIX_ITEM_KIND = Object.freeze({
  RESIDUAL: 'residual',
  PRE_DECIDED: 'pre_decided',
  SCHEDULED: 'scheduled',
  DEFECT: 'defect',
});

/**
 * Resolve absolute ledger path.
 * @param {{ root?: string, ledgerPath?: string }} [opts]
 */
export function resolveLedgerPath(opts = {}) {
  if (opts.ledgerPath) return path.resolve(opts.ledgerPath);
  const root = opts.root ? path.resolve(opts.root) : process.cwd();
  return path.join(root, FIX_ITEM_LEDGER_REL);
}

/**
 * Resolve absolute degraded path.
 * @param {{ root?: string, degradedPath?: string }} [opts]
 */
export function resolveDegradedPath(opts = {}) {
  if (opts.degradedPath) return path.resolve(opts.degradedPath);
  const root = opts.root ? path.resolve(opts.root) : process.cwd();
  return path.join(root, DEGRADED_REL);
}

/**
 * Empty ledger document.
 * @returns {object}
 */
export function emptyFixItemLedger() {
  return {
    schema: FIX_ITEM_LEDGER_SCHEMA,
    version: 1,
    residual_cap: FIX_ITEM_RESIDUAL_CAP,
    max_waves: FIX_ITEM_MAX_WAVES,
    items: [],
    updated_at: null,
  };
}

/**
 * Read the ledger (missing → empty).
 * @param {{ root?: string, ledgerPath?: string }} [opts]
 */
export function readFixItemLedger(opts = {}) {
  const p = resolveLedgerPath(opts);
  if (!fs.existsSync(p)) {
    return { ok: true, exists: false, path: p, ledger: emptyFixItemLedger() };
  }
  try {
    const raw = fs.readFileSync(p, 'utf8');
    const ledger = JSON.parse(raw);
    if (!ledger || typeof ledger !== 'object' || !Array.isArray(ledger.items)) {
      return {
        ok: false,
        exists: true,
        path: p,
        error: 'fix_item_ledger_malformed',
        ledger: emptyFixItemLedger(),
      };
    }
    return { ok: true, exists: true, path: p, ledger };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      path: p,
      error: 'fix_item_ledger_unreadable',
      message: String(e?.message ?? e),
      ledger: emptyFixItemLedger(),
    };
  }
}

/**
 * Whether a row counts against the residual cap.
 * @param {object} item
 */
export function countsAgainstCap(item) {
  if (!item || typeof item !== 'object') return false;
  if (item.counts_against_cap === false) return false;
  if (item.kind === FIX_ITEM_KIND.PRE_DECIDED) return false;
  if (item.kind === FIX_ITEM_KIND.SCHEDULED) return false;
  if (item.kind === FIX_ITEM_KIND.DEFECT && item.counts_against_cap === false) {
    return false;
  }
  return item.kind === FIX_ITEM_KIND.RESIDUAL || item.counts_against_cap === true;
}

/**
 * Count residual items that burn the cap.
 * @param {object} ledger
 */
export function residualCount(ledger) {
  const items = Array.isArray(ledger?.items) ? ledger.items : [];
  return items.filter(countsAgainstCap).length;
}

/**
 * Cap evaluation: residual ≤ 6, else overflow → DEGRADED + HALT.
 * @param {object} ledger
 */
export function evaluateCap(ledger) {
  const residual = residualCount(ledger);
  const cap = ledger?.residual_cap ?? FIX_ITEM_RESIDUAL_CAP;
  const overflow = residual > cap;
  return {
    residual,
    cap,
    ok: !overflow,
    overflow,
    halt: overflow
      ? {
          code: 'FIX_ITEM_CAP_OVERFLOW',
          message:
            `Residual fix-item count ${residual} exceeds cap ${cap}. `
            + 'Overflow rows go to artifacts/degraded.json; HALT for John '
            + '(Wave 19: DEGRADED cannot green criterion 13 without his signature).',
        }
      : null,
  };
}

/**
 * Append one fix item under the S10 lock + atomic write.
 * Idempotent by `id` when present: re-append updates the row in place.
 *
 * @param {object} item
 * @param {{ root?: string, ledgerPath?: string, at?: string }} [opts]
 */
export function appendFixItem(item, opts = {}) {
  if (!item || typeof item !== 'object' || !item.id) {
    return {
      ok: false,
      error: 'fix_item_requires_id',
      message: 'Fix items need a stable id.',
    };
  }

  const p = resolveLedgerPath(opts);
  fs.mkdirSync(path.dirname(p), { recursive: true });

  const at = opts.at ?? new Date().toISOString();

  return withFileLock(p, () => {
    let ledger = emptyFixItemLedger();
    let onDisk = null;
    if (fs.existsSync(p)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (parsed && Array.isArray(parsed.items)) {
          onDisk = parsed;
          // Deep clone so mutation below never aliases the on-disk snapshot.
          ledger = JSON.parse(JSON.stringify(parsed));
        }
      } catch {
        // start fresh if torn — atomic rewrite recovers
      }
    }

    const nextItem = {
      ...item,
      kind: item.kind ?? FIX_ITEM_KIND.RESIDUAL,
      counts_against_cap:
        item.counts_against_cap !== undefined
          ? Boolean(item.counts_against_cap)
          : item.kind === FIX_ITEM_KIND.RESIDUAL || item.kind == null,
      recorded_at: item.recorded_at ?? at,
    };

    const idx = ledger.items.findIndex((r) => r.id === nextItem.id);
    if (idx >= 0) ledger.items[idx] = { ...ledger.items[idx], ...nextItem };
    else ledger.items.push(nextItem);

    ledger.schema = FIX_ITEM_LEDGER_SCHEMA;
    ledger.residual_cap = FIX_ITEM_RESIDUAL_CAP;
    ledger.max_waves = FIX_ITEM_MAX_WAVES;
    ledger.updated_at = at;

    const cap = evaluateCap(ledger);

    // IDEMPOTENT WRITER (journal 0070/0074 thrash fix): when the SEMANTIC
    // content (everything except updated_at / per-item recorded_at) is
    // unchanged from what is on disk, DO NOT WRITE AT ALL — the file stays
    // byte-identical and produces no git delta. Only a genuine content change
    // may advance the timestamps.
    if (onDisk && jsonSemanticallyEqual(onDisk, ledger, LEDGER_VOLATILE_KEYS)) {
      const existingIdx = onDisk.items.findIndex((r) => r.id === nextItem.id);
      return {
        ok: true,
        unchanged: true,
        path: p,
        item: existingIdx >= 0 ? onDisk.items[existingIdx] : nextItem,
        ledger: onDisk,
        residual: cap.residual,
        cap: cap.cap,
        overflow: cap.overflow,
        halt: cap.halt,
      };
    }

    writeFileAtomicSync(p, `${JSON.stringify(ledger, null, 2)}\n`);

    return {
      ok: true,
      unchanged: false,
      path: p,
      item: nextItem,
      ledger,
      residual: cap.residual,
      cap: cap.cap,
      overflow: cap.overflow,
      halt: cap.halt,
    };
  });
}

/**
 * Write the DEGRADED overflow list (Wave 19 signature required to green SC13).
 * @param {object[]} overflowItems
 * @param {{ root?: string, degradedPath?: string, reason?: string, at?: string }} [opts]
 */
export function writeDegradedList(overflowItems, opts = {}) {
  const p = resolveDegradedPath(opts);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const doc = {
    schema: 'ecgberht-degraded-v0',
    signed: false,
    signer: null,
    signed_at: null,
    reason:
      opts.reason ??
      'Fix-item residual cap overflow — DEGRADED rows cannot green criterion 13 without John signature (Wave 19).',
    items: Array.isArray(overflowItems) ? overflowItems : [],
    recorded_at: opts.at ?? new Date().toISOString(),
  };
  // Idempotent: semantically-unchanged overflow list leaves the file untouched.
  try {
    const existing = JSON.parse(fs.readFileSync(p, 'utf8'));
    if (jsonSemanticallyEqual(existing, doc, LEDGER_VOLATILE_KEYS)) {
      return { ok: true, unchanged: true, path: p, degraded: existing };
    }
  } catch {
    // absent/torn → write
  }
  writeFileAtomicSync(p, `${JSON.stringify(doc, null, 2)}\n`);
  return { ok: true, unchanged: false, path: p, degraded: doc };
}

/**
 * Apply cap: if residual overflow, write DEGRADED and return HALT.
 * Does NOT fire HALT for pre-decided rows.
 * @param {{ root?: string, ledgerPath?: string, degradedPath?: string }} [opts]
 */
export function applyCapOrHalt(opts = {}) {
  const read = readFixItemLedger(opts);
  const cap = evaluateCap(read.ledger);
  if (!cap.overflow) {
    return {
      ok: true,
      residual: cap.residual,
      cap: cap.cap,
      halt: null,
      degraded: null,
    };
  }
  const residualItems = (read.ledger.items ?? []).filter(countsAgainstCap);
  const overflowItems = residualItems.slice(cap.cap);
  const degraded = writeDegradedList(overflowItems, opts);
  return {
    ok: false,
    residual: cap.residual,
    cap: cap.cap,
    halt: cap.halt,
    degraded,
    overflow_items: overflowItems,
  };
}

/**
 * Concurrent-append helper used by T-DUR-S10 (N processes × M rows).
 * @param {string} ledgerPath
 * @param {object} item
 */
export function appendFixItemAtPath(ledgerPath, item) {
  return appendFixItem(item, { ledgerPath });
}

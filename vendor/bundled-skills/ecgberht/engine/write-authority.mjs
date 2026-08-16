/**
 * Write-authority: Face may rewrite human narrative; Strip is append-only
 * for instruments/receipts. Silent in-place Strip clock rewrite is rejected.
 *
 * W9 ADDED THE INDEX SIDE OF THIS AUTHORITY, and added it here rather than inventing a
 * second one. appendStripReceipt and appendStripInstrument stay exactly what they were -
 * PURE functions that decide what an append means and refuse what it may not do - and the
 * two *Durable entry points below wrap them: authority first, then the durable
 * source-of-truth write, then exactly one derived-row-v1 appended to the ONE portfolio index
 * before the call returns. Every existing caller of the pure functions is untouched.
 *
 * Why wrap rather than fold the index into the pure function: a function that both decides
 * and writes cannot be used to decide, and half this engine calls these to compute a next
 * strip without touching a disk. The wrapper is the write path; the wrapped function stays
 * the authority.
 *
 * WHERE THE BYTES GO, and why it is not strip.json. The index discovers content through the
 * frozen inventory-v1 paths (`<root>/receipts/*.json`, `<root>/instruments/*.json`), so that
 * is where a durable append writes the appended entry: a file written anywhere else produces
 * a row on the write path that no rebuild could reproduce, which is precisely the fork the
 * single shared derive.mjs exists to prevent. The strip that comes back is still the
 * caller's to persist through whatever surface it already uses - this wrapper does not
 * quietly become a second strip writer.
 */

import { FACE_NARRATIVE_FIELDS, parseStrip } from './face-strip.mjs';
import { ingestWrite, relPathFor, requireItemId } from './portfolio/ingest.mjs';
import { CLASS } from './portfolio/inventory.mjs';

/** Fields that may be rewritten on Face (human narrative / north-star / why-stakes). */
export const FACE_REWRITABLE = FACE_NARRATIVE_FIELDS;

/**
 * Strip clock / instrument projection fields — not silently rewritten in place.
 * Updates flow only via append instrument/receipt or explicit heal re-sync.
 */
export const STRIP_CLOCK_FIELDS = Object.freeze([
  'as_of',
  'phase',
  'active_effort',
  'effort_status',
  'human_wait',
  'capacity',
  'negative_heartbeat',
  'anti_starvation_age_days',
  'tool_depth_cell',
  'next_recommended',
  'why_next',
  'grasscatch',
  'uncertainty_flags',
]);

/** Append-only history bags — silent rewrite of prior entries is forbidden. */
export const STRIP_HISTORY_FIELDS = Object.freeze(['instruments', 'receipts']);

/**
 * All Strip fields that reject silent in-place mutation (clocks + history).
 */
export const STRIP_PROTECTED_FIELDS = Object.freeze([
  ...STRIP_CLOCK_FIELDS,
  ...STRIP_HISTORY_FIELDS,
]);

/**
 * Rewrite Face narrative fields. Always allowed under write authority.
 * @param {object} faceNarrative current narrative map
 * @param {object} patch partial narrative fields
 * @returns {{ ok: true, narrative: object, rewritten: string[] }}
 */
export function rewriteFaceNarrative(faceNarrative, patch = {}) {
  const base =
    faceNarrative && typeof faceNarrative === 'object' && !Array.isArray(faceNarrative)
      ? { ...faceNarrative }
      : {};
  const rewritten = [];
  const next = { ...base };

  for (const key of FACE_REWRITABLE) {
    if (Object.prototype.hasOwnProperty.call(patch, key)) {
      next[key] = patch[key];
      rewritten.push(key);
    }
  }

  // Allow nested narrative object under { narrative: {...} }
  if (patch.narrative && typeof patch.narrative === 'object') {
    for (const key of FACE_REWRITABLE) {
      if (Object.prototype.hasOwnProperty.call(patch.narrative, key)) {
        next[key] = patch.narrative[key];
        if (!rewritten.includes(key)) rewritten.push(key);
      }
    }
  }

  return {
    ok: true,
    authority: 'face_human_narrative',
    narrative: next,
    rewritten,
  };
}

/**
 * Attempt silent in-place Strip clock/history mutation — always rejected.
 * Callers must use appendStripInstrument / appendStripReceipt or healResync.
 * Does not mutate the input strip (returns strip_unchanged: true).
 * @param {object} strip
 * @param {object} patch field → value
 * @returns {{ ok: false, error: 'strip_in_place_mutation_rejected', ... }}
 */
export function mutateStripInPlace(strip, patch = {}) {
  const keys = Object.keys(patch || {});
  const attempted = keys.filter((k) => STRIP_PROTECTED_FIELDS.includes(k));
  // Snapshot proof: never touch the caller's strip object
  const beforeAsOf =
    strip && typeof strip === 'object' ? strip.as_of : undefined;
  const beforeInstLen =
    strip && typeof strip === 'object' && Array.isArray(strip.instruments)
      ? strip.instruments.length
      : 0;

  return {
    ok: false,
    error: 'strip_in_place_mutation_rejected',
    message:
      'Strip clocks and instrument/receipt history are append-only; silent in-place rewrite is rejected. Append an instrument/receipt or use explicit heal re-sync.',
    attempted_fields: attempted.length ? attempted : keys,
    protected_fields: [...STRIP_PROTECTED_FIELDS],
    allowed: ['appendStripInstrument', 'appendStripReceipt', 'healResync'],
    strip_unchanged: true,
    // Callers may assert input identity was not rewritten
    input_as_of: beforeAsOf,
    input_instruments_length: beforeInstLen,
  };
}

/**
 * Append an instrument entry; optionally refresh projection from the entry.
 * Never rewrites prior instruments[] entries.
 * @param {object} strip
 * @param {object} instrument
 * @param {{ apply_to_projection?: boolean }} [opts]
 */
export function appendStripInstrument(strip, instrument, opts = {}) {
  const parsed = parseStrip(strip);
  if (!parsed.ok) return { ok: false, ...parsed };

  if (!instrument || typeof instrument !== 'object' || Array.isArray(instrument)) {
    return { ok: false, error: 'instrument_not_object' };
  }

  const next = {
    ...parsed.strip,
    instruments: [...parsed.strip.instruments, { ...instrument, _kind: instrument._kind ?? 'instrument' }],
    receipts: [...parsed.strip.receipts],
  };

  if (opts.apply_to_projection !== false) {
    applyProjectionFromEntry(next, instrument);
  }

  return {
    ok: true,
    authority: 'strip_append_only',
    strip: next,
    appended: 'instrument',
  };
}

/**
 * Append a receipt entry; never rewrites prior receipts[].
 * @param {object} strip
 * @param {object} receipt
 * @param {{ apply_to_projection?: boolean }} [opts]
 */
export function appendStripReceipt(strip, receipt, opts = {}) {
  const parsed = parseStrip(strip);
  if (!parsed.ok) return { ok: false, ...parsed };

  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) {
    return { ok: false, error: 'receipt_not_object' };
  }

  const next = {
    ...parsed.strip,
    instruments: [...parsed.strip.instruments],
    receipts: [...parsed.strip.receipts, { ...receipt, _kind: receipt._kind ?? 'receipt' }],
  };

  if (opts.apply_to_projection === true) {
    applyProjectionFromEntry(next, receipt);
  }

  return {
    ok: true,
    authority: 'strip_append_only',
    strip: next,
    appended: 'receipt',
  };
}

/**
 * Apply projection tip fields from a newly appended instrument/receipt.
 * Never rewrites prior instruments[] / receipts[] entries (those are copied
 * before this runs). grasscatch / uncertainty_flags merge unique strings
 * (append-union) so an append cannot silently drop prior park/flags.
 * @param {object} strip mutable clone (post-append history already set)
 * @param {object} entry
 */
function applyProjectionFromEntry(strip, entry) {
  for (const key of STRIP_CLOCK_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(entry, key) && entry[key] !== undefined) {
      if (key === 'grasscatch' || key === 'uncertainty_flags') {
        const prior = Array.isArray(strip[key]) ? strip[key] : [];
        const incoming = Array.isArray(entry[key])
          ? entry[key]
          : entry[key] != null
            ? [entry[key]]
            : [];
        const merged = [];
        const seen = new Set();
        for (const item of [...prior, ...incoming]) {
          const token = typeof item === 'string' ? item : JSON.stringify(item);
          if (seen.has(token)) continue;
          seen.add(token);
          merged.push(item);
        }
        strip[key] = merged;
      } else if (key === 'negative_heartbeat' && entry[key] && typeof entry[key] === 'object') {
        strip[key] = { ...entry[key] };
      } else {
        strip[key] = entry[key];
      }
    }
  }
}

// -- W9: the durable, indexed half of the same authority ----------------------

/**
 * The bytes one appended strip entry is stored as.
 *
 * Pretty-printed with a trailing newline because these files are read by humans as often as
 * by the engine, and stable formatting means a hand-inspected file and a written one hash
 * the same. The bytes are what the row's sha256 is taken over, so this function is part of
 * the contract rather than a formatting preference.
 *
 * @param {object} entry @returns {string}
 */
export function stripEntryBytes(entry) {
  return `${JSON.stringify(entry, null, 2)}\n`;
}

/**
 * Append an entry through the pure authority, persist it at its inventory-v1 discovery path,
 * and emit exactly one derived-row-v1 - in the frozen W9 order.
 *
 * @param {string} className CLASS.RECEIPT or CLASS.INSTRUMENT
 * @param {(strip: object, entry: object, opts: object) => object} authority
 * @param {string} projectRoot @param {object} strip @param {object} entry
 * @param {object} opts
 * @returns {object}
 */
function appendStripEntryDurable(className, authority, projectRoot, strip, entry, opts) {
  const appended = authority(strip, entry, opts);
  if (!appended.ok) return appended;

  const bag = className === CLASS.RECEIPT ? appended.strip.receipts : appended.strip.instruments;
  const stored = bag[bag.length - 1];

  const id = requireItemId(className, stored);
  if (!id.ok) {
    // Nothing is written and nothing is indexed. The strip the authority computed is still
    // returned: refusing to persist an unidentifiable entry is not a reason to throw away
    // the caller's in-memory work.
    return { ...appended, ok: false, ...id.outcome, ingest: id.outcome, indexed: false };
  }

  const ingest = ingestWrite({
    class: className,
    project_id: opts.project_id,
    root: projectRoot,
    rel: opts.rel ?? relPathFor(className, id.id),
    bytes: stripEntryBytes(stored),
    home: opts.home,
    paths: opts.paths,
    env: opts.env,
    appendOpts: opts.appendOpts,
    beforeFlush: opts.beforeFlush,
  });

  return {
    ...appended,
    // The source-of-truth write STANDS even when the index append fails, so `ok` reports the
    // whole verb while `sot_written` reports the file. An operator told only "failed" would
    // reasonably conclude their receipt was lost, and it is not.
    ok: ingest.ok === true,
    code: ingest.code ?? null,
    status: ingest.status ?? null,
    text: ingest.text ?? '',
    ingest,
    indexed: ingest.ok === true,
    sot_written: ingest.sot_written === true,
    row: ingest.row ?? null,
    seq: ingest.seq ?? null,
    // W15. The durability receipt this write asked for, surfaced beside the row so a caller
    // can tell "indexed" from "asked to be committed" without re-reading the log. Null when
    // the flush failed: an intent that is not in the log is not a request anybody received.
    intent: ingest.intent ?? null,
    intent_seq: ingest.intent_seq ?? null,
    intent_emitted: ingest.intent_emitted === true,
    freshness: ingest.freshness,
    path: ingest.path ?? null,
    trace: ingest.trace ?? [],
  };
}

/**
 * appendStripReceipt, made durable and findable.
 *
 * @param {string} projectRoot the registered root the receipt belongs to
 * @param {object} strip @param {object} receipt
 * @param {{project_id: string, home?: string, paths?: object, env?: object, rel?: string,
 *          apply_to_projection?: boolean, beforeFlush?: Function, appendOpts?: object}} opts
 * @returns {object}
 */
export function appendStripReceiptDurable(projectRoot, strip, receipt, opts = {}) {
  return appendStripEntryDurable(
    CLASS.RECEIPT,
    appendStripReceipt,
    projectRoot,
    strip,
    receipt,
    opts,
  );
}

/**
 * appendStripInstrument, made durable and findable. A literal peer of the receipt path
 * above - same ordering, same row shape, its own `proj` field set - which is class-symmetry
 * leg 3 expressed as code rather than as a promise.
 *
 * @param {string} projectRoot @param {object} strip @param {object} instrument
 * @param {{project_id: string, home?: string, paths?: object, env?: object, rel?: string,
 *          apply_to_projection?: boolean, beforeFlush?: Function, appendOpts?: object}} opts
 * @returns {object}
 */
export function appendStripInstrumentDurable(projectRoot, strip, instrument, opts = {}) {
  return appendStripEntryDurable(
    CLASS.INSTRUMENT,
    appendStripInstrument,
    projectRoot,
    strip,
    instrument,
    opts,
  );
}

/**
 * Guard helper: is this patch a forbidden Strip in-place clock/history rewrite?
 * @param {object} patch
 */
export function isStripClockPatch(patch) {
  if (!patch || typeof patch !== 'object') return false;
  return Object.keys(patch).some((k) => STRIP_PROTECTED_FIELDS.includes(k));
}

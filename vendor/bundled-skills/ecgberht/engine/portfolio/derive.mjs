/**
 * W9 - derive.mjs: the ONE function that turns bytes on disk into a derived-row-v1.
 *
 * WHY THIS MODULE EXISTS AND WHY IT IS NOT PART OF EITHER CALLER. There are exactly two
 * producers of DERIVED rows in this system, and they run at completely different moments:
 *
 *   the WRITE PATH  (engine/portfolio/ingest.mjs, this wave) derives a row the instant a
 *                   source-of-truth file is written, so the item is findable immediately;
 *   the REBUILDER   (W10, and the W8 startup sweep in divergence.mjs already) derives a row
 *                   from a file it discovers later, with no memory of who wrote it.
 *
 * If those two derived rows their own way, the portfolio would carry two shapes of the same
 * fact: a row written by a lucky process would differ from a row regenerated for the same
 * bytes by an unlucky one, and W10's byte-equal rebuild would be false by construction - not
 * because anything is broken, but because "the row" would never have been one thing. So the
 * derivation is ONE pure function with no I/O, no clock, and no lock, imported by both. The
 * W10 equivalence test is what PROVES they cannot fork; this module is what makes the proof
 * available to make.
 *
 * W8 wrote the first version of this function inside engine/portfolio/divergence.mjs and
 * said, in that file's own header, that W9 would land derive.mjs as its permanent home. That
 * is what this file is. divergence.mjs now imports and re-exports it rather than keeping a
 * copy: a re-export cannot drift, and a copy is exactly the fork the plan forbids.
 *
 * WHAT `seq` AND `written_at` ARE NOT DOING HERE. Both are absent from the row on purpose.
 * The append primitive allocates them under the portfolio lock and REFUSES a payload that
 * carries either (engine/append-log.mjs, RESERVED_EVENT_FIELDS), so a row physically cannot
 * smuggle in its own total order. That is also what makes the same bytes derive to the same
 * row on two machines at two instants: everything in here is a function of its arguments.
 *
 * THE `proj` PROJECTION AND WHY OVERFLOW IS FLAGGED RATHER THAN CUT. `proj` is the ONLY
 * thing a later `--contains` query searches. A field silently truncated at 256 characters
 * would make a search result quietly WRONG - the operator searches for a word that is in the
 * file, gets no hit, and concludes it is not there. So a capped value sets
 * `proj_truncated:true` on the row, and every surface that renders a result can say the
 * content was cut. A cap you cannot see is worse than a cap you cannot raise.
 *
 * Stdlib only, and deliberately no `node:fs` at all: this module cannot read a file even by
 * accident, which is what keeps "derive" from quietly becoming "derive and go and look".
 */

import { ORDERING_FIELD, WALL_CLOCK_FIELD } from '../append-log.mjs';
import { canonicalJson } from './canonical.mjs';
import { CAPS } from './caps.mjs';
// W18. checkpoint.mjs is a LEAF that does not import this module, so the dependency runs one
// way only and no cycle is possible. It is imported HERE, rather than at each of the half-dozen
// places that read a DERIVED history, so a compacted log unfolds at exactly one call site.
import { checkpointRowOf, expandCheckpoints } from './checkpoint.mjs';
import { hashBytes } from './commit-intent.mjs';
import { CLASS, parseBytes, toPosix } from './inventory.mjs';

/** The frozen derivation's version. Changing the row shape means derive-v2. */
export const DERIVE_VERSION = 'derive-v1';

/** The DERIVED event's type tag and version, frozen in the plan as derived-row-v1. */
export const DERIVED_EVENT_TYPE = 'derived';
export const DERIVED_ROW_VERSION = 1;

/**
 * The frozen derived-row-v1 field set, minus the two the append primitive owns. Stated as
 * data so a test can enumerate the shape instead of restating it, and so a field added by a
 * later wave is a visible edit here rather than a surprise in the bytes.
 */
export const DERIVED_ROW_FIELDS = Object.freeze([
  't',
  'v',
  'class',
  'project_id',
  'path',
  'sha256',
  'byte_len',
  'supersedes',
  'proj',
]);

/** The overflow flag derived-row-v1 sets rather than truncating in silence. */
export const PROJ_TRUNCATED_FIELD = 'proj_truncated';

/**
 * The three tracked content classes. The identity marker is discovered by inventory-v1 too
 * and is deliberately NOT derived into a content row: it is the NATIVE mirror of an identity
 * the log already carries, and deriving a content row from it would put membership in two
 * stores.
 *
 * @type {ReadonlyArray<string>}
 */
export const DERIVABLE_CLASSES = Object.freeze([
  CLASS.RECEIPT,
  CLASS.INSTRUMENT,
  CLASS.ROADMAP_EVENT,
]);

/**
 * The per-class `proj` projection, frozen in the plan's W9 deliverables. instrument and
 * roadmap-event are literal peers of receipt here - each has its own field set, named in
 * full, rather than a receipt shape with two of the names changed.
 */
export const PROJ_FIELDS = Object.freeze({
  [CLASS.RECEIPT]: Object.freeze(['receipt_id', 'kind', 'title', 'subject_ids']),
  [CLASS.INSTRUMENT]: Object.freeze(['instrument_id', 'name', 'kind', 'status']),
  [CLASS.ROADMAP_EVENT]: Object.freeze(['event_id', 'roadmap_id', 'kind', 'title', 'step_status']),
});

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** @param {string} className @returns {boolean} whether this class produces DERIVED rows */
export function isDerivableClass(className) {
  return DERIVABLE_CLASSES.includes(String(className));
}

/**
 * Cap one `proj` value, reporting overflow rather than performing it in silence.
 *
 * @param {unknown} value
 * @returns {{value: unknown, truncated: boolean}}
 */
export function capProjValue(value) {
  if (typeof value === 'string' && value.length > CAPS.proj_field_chars) {
    return { value: value.slice(0, CAPS.proj_field_chars), truncated: true };
  }
  if (Array.isArray(value)) {
    const entries = value.slice(0, CAPS.proj_array_entries);
    let truncated = entries.length < value.length;
    const capped = entries.map((entry) => {
      const inner = capProjValue(entry);
      if (inner.truncated) truncated = true;
      return inner.value;
    });
    return { value: capped, truncated };
  }
  return { value: value === undefined ? null : value, truncated: false };
}

/**
 * The `proj` projection for one class, from the parsed source record.
 *
 * Every declared field is present, `null` when the source does not carry it. An absent key
 * and a null value would otherwise be two shapes of the same fact, and two shapes is one
 * more than a byte-equal rebuild can survive.
 *
 * @param {string} className @param {object|null} record
 * @returns {{proj: object, truncated: boolean}}
 */
export function projectionFor(className, record) {
  const fields = PROJ_FIELDS[className] ?? [];
  const source = isPlainObject(record) ? record : {};
  const proj = {};
  let truncated = false;
  for (const field of [...fields].sort()) {
    const capped = capProjValue(source[field]);
    if (capped.truncated) truncated = true;
    proj[field] = capped.value;
  }
  return { proj, truncated };
}

/**
 * Parse the bytes of a file into the record `proj` projects from.
 *
 * inventory-v1's parseBytes is the gate - it is the one place EMPTY, INVALID_UTF8 and
 * MOJIBAKE are decided, in that order, and a row derived from mojibake bytes would carry a
 * faithful hash of damage into an append-only log forever. Only once it passes are the bytes
 * parsed a second time here for the RAW object, because parseBytes projects the inventory
 * field set and `proj` is a different, wider one.
 *
 * @param {string} className @param {Buffer|Uint8Array|string} bytes @param {string} [absPath]
 * @returns {{ok: boolean, record: object|null, reason: string|null, detail: string|null}}
 */
export function sourceRecordFor(className, bytes, absPath) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
  const parsed = parseBytes(className, buffer, { path: absPath });
  if (!parsed.ok) {
    return { ok: false, record: null, reason: parsed.reason ?? null, detail: parsed.detail ?? null };
  }
  const text = buffer.toString('utf8');
  try {
    if (className === CLASS.ROADMAP_EVENT) {
      // A JSONL carrier is ONE file and therefore ONE row (identity is the path), so the
      // projection comes from its first event. The whole file's bytes are still what the
      // hash and the byte length are taken over, so nothing after the first line is
      // unverifiable - it is unprojected, which is a different and stated thing.
      //
      // The W9 write path sidesteps that residue entirely by writing ONE event per carrier
      // file (engine/portfolio/ingest.mjs), which is why a just-written roadmap event is
      // projected and findable rather than hidden behind an older sibling. A hand-authored
      // multi-event carrier is still ingested, still hashed whole, and still honest about
      // projecting only its first event.
      const first = text.split('\n').find((line) => line.trim() !== '');
      return { ok: true, record: JSON.parse(String(first)), reason: null, detail: null };
    }
    return { ok: true, record: JSON.parse(text), reason: null, detail: null };
  } catch (err) {
    return {
      ok: false,
      record: null,
      reason: parsed.reason ?? null,
      detail: String((err && err.message) || err),
    };
  }
}

/**
 * THE ONE DERIVATION. `deriveRow(class, projectId, rootRelPath, bytes)` -> a derived-row-v1
 * payload, exactly as the plan names it.
 *
 * Pure: the same four arguments produce the same row on any machine at any instant. That is
 * not a nice property, it is the whole mechanism - the write path and the rebuilder pass the
 * same four values for the same file, so their rows are identical rather than merely alike.
 *
 * @param {string} className one of DERIVABLE_CLASSES
 * @param {string} projectId the minted project_id (never derived from a path)
 * @param {string} rootRelPath root-relative; separators are normalized to POSIX here
 * @param {Buffer|Uint8Array|string} bytes the bytes that are on disk, undecoded
 * @param {{supersedes?: number|null, record?: object|null}} [opts]
 * @returns {Readonly<object>} a derived-row-v1 payload, without `seq` and `written_at`
 */
export function deriveRow(className, projectId, rootRelPath, bytes, opts = {}) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
  const rel = toPosix(String(rootRelPath));
  const record = opts.record === undefined
    ? sourceRecordFor(className, buffer, rel).record
    : opts.record;
  const projected = projectionFor(className, record);

  const row = {
    t: DERIVED_EVENT_TYPE,
    v: DERIVED_ROW_VERSION,
    class: className,
    project_id: String(projectId),
    // The path is stored AS WRITTEN (POSIX separators, original case) and lowercased only
    // for comparison - see rowIdentity. Storing it lowercased would make the row unable to
    // name the file it describes on a case-sensitive filesystem.
    path: rel,
    sha256: hashBytes(buffer),
    byte_len: buffer.length,
    supersedes: opts.supersedes === undefined ? null : opts.supersedes,
    proj: projected.proj,
  };
  if (projected.truncated) row[PROJ_TRUNCATED_FIELD] = true;
  return Object.freeze(row);
}

/**
 * The W8 name for the same function, kept so the sweep, its tests and the multi-process
 * fixtures keep working. An alias cannot fork; a second implementation would.
 *
 * @type {typeof deriveRow}
 */
export const derivedRowFrom = deriveRow;

/** @param {unknown} event @returns {boolean} */
export function isDerivedEvent(event) {
  return (
    isPlainObject(event)
    && event.t === DERIVED_EVENT_TYPE
    && Number(event.v) === DERIVED_ROW_VERSION
    && typeof event.project_id === 'string'
    && typeof event.path === 'string'
  );
}

/**
 * The identity of a row: (project_id, class, path). Paths are compared lowercased because
 * Windows resolves `Receipts/A.json` and `receipts/a.json` to one file, and two rows for one
 * file would double-count it.
 *
 * The separator is NUL because it is the one character none of the three parts can contain:
 * a project_id, a class name or a path carrying whatever separator we picked could otherwise
 * make two different identities produce one string, and two files sharing an identity is two
 * files sharing a row.
 *
 * @param {{project_id: string, class: string, path: string}} row @returns {string}
 */
export function rowIdentity(row) {
  return [String(row.project_id), String(row.class), String(row.path).toLowerCase()].join(' ');
}

/**
 * The bytes a row IS, ignoring the two fields the log allocates.
 *
 * This is the comparison the kill-window test makes and the one W10's equivalence test will
 * make: a regenerated row and the row an uncrashed run wrote sit at different `seq`s and
 * were written at different instants, and everything else about them must be identical - so
 * the fingerprint subtracts exactly those two and nothing else.
 *
 * @param {object} row @returns {string} canonical JSON of the row's content fields
 */
export function rowFingerprint(row) {
  const content = {};
  for (const key of Object.keys(row).sort()) {
    if (key === ORDERING_FIELD || key === WALL_CLOCK_FIELD) continue;
    content[key] = row[key];
  }
  return canonicalJson(content);
}

/**
 * Index the DERIVED rows a log already carries, newest last.
 *
 * W18: A COMPACTED LOG IS THE SAME LOG TO EVERY CALLER OF THIS FUNCTION. After compaction the
 * latest row for a file sits inside a checkpoint-row-v1 rather than on its own line, and the
 * versions before it are lineage entries whose bodies were retired. Unfolding the checkpoint
 * here - and only here - is what makes the rebuilder, the verifier and the write path's
 * lineage lookup behave identically on either side of the compaction boundary. Each of them
 * asking the question its own way is precisely the fork this module exists to prevent, so the
 * unfolding is one line at one call site rather than a rule six files have to remember.
 *
 * The HISTORY a compacted log yields is one row long: the surviving body. Its superseded
 * versions are still findable and verifiable through checkpoint.mjs's lineage - identity, hash
 * and order - but they are no longer DERIVED events, because their bodies are not here. That
 * is D-4's stated cost (NS-Q1) rather than an omission of this function's.
 *
 * @param {ReadonlyArray<object>} events
 * @returns {Map<string, object[]>} identity -> rows in seq order
 */
export function derivedRowsInLog(events) {
  const byIdentity = new Map();
  for (const raw of events ?? []) {
    const event = checkpointRowOf(raw) ?? raw;
    if (!isDerivedEvent(event)) continue;
    const key = rowIdentity(event);
    const list = byIdentity.get(key);
    if (list === undefined) byIdentity.set(key, [event]);
    else list.push(event);
  }
  return byIdentity;
}

/**
 * Re-exported so a caller that iterates raw events itself - rather than asking for a history -
 * unfolds them the same way this module does, instead of writing a second unfolding.
 */
export { expandCheckpoints };

/**
 * The seq a new row for this identity supersedes, or null if this file has never been
 * indexed. D-4 keeps the whole lineage, so a rewrite is a NEW row pointing at the one it
 * replaced rather than an edit of the old one - the log is append-only and nothing in it is
 * ever revised.
 *
 * @param {ReadonlyArray<object>} events @param {{project_id: string, class: string, path: string}} row
 * @returns {number|null}
 */
export function supersedesSeqFor(events, row) {
  const history = derivedRowsInLog(events).get(rowIdentity(row)) ?? [];
  if (history.length === 0) return null;
  const latest = history[history.length - 1];
  const seq = Number(latest[ORDERING_FIELD]);
  return Number.isInteger(seq) ? seq : null;
}

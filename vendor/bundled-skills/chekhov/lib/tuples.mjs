/**
 * Chekhov tuples — schema 1 — in SIDECAR ledgers (W3; F3, John's call).
 *
 * YAML tuples live in <file>.ledger.yaml BESIDE each markdown file — one
 * sidecar per prose file, written atomically through lib/store.mjs under the
 * root lock. The prose file is NEVER written by this module and never holds a
 * machine block. Receipt anchoring: an exact span match stands; a fuzzy match
 * yields a receipt-drift record with a proposed anchor and the STORED span
 * unchanged; re-anchoring happens only at accept.
 *
 * Core fields: id, value, interval, lock, receipt — plus kind and schema: 1.
 * The reader refuses a tuple with no schema or an unknown schema and never
 * guesses. Lock rungs: candidate and locked only. Ids are stable slugs; a
 * rename is an alias entry, never an id change (an id change is refused).
 */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { atomicWriteFile, withLock } from './store.mjs';
import { intervalContainsCoord, intervalOverlaps, parseCoord, validateClaim, validateInterval } from './pack.mjs';

export const TUPLE_SCHEMA = 1;
export const KINDS = Object.freeze(['fact', 'thread', 'alias', 'decision', 'structural']);
export const LOCK_RUNGS = Object.freeze(['candidate', 'locked']);
export const CORE_FIELDS = Object.freeze(['id', 'value', 'interval', 'lock', 'receipt']);
export const OPTIONAL_FIELDS = Object.freeze([
  'unit',
  'accepted_by',
  'accepted_on',
  'superseded_by',
  'allow_terms',
  'authorial_rename',
  'governs',
  'depends_on',
  'orders',
  'cost_of_change',
  'acceptance_receipt', 'edited_by', 'authored_by', 'question', 'deferred', 'source', 'expected',
]);
const RECEIPT_FIELDS = Object.freeze(['span', 'heading_path', 'line_hint', 'date']);

// Stable slugs: dot-separated lowercase segments (char.elra, series.book_count).
const SLUG_RE = /^[a-z][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$/;

export class TupleError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

/** Validate one tuple against schema 1. Refuses; never guesses; never repairs. */
export function validateTuple(t) {
  if (!t || typeof t !== 'object') throw new TupleError('invalid_tuple', 'tuple is not a map');
  if (!('schema' in t)) throw new TupleError('unversioned_tuple', `tuple ${t.id || '(no id)'} has no schema field — refused, never guessed`);
  if (t.schema !== TUPLE_SCHEMA) {
    throw new TupleError('unknown_schema', `tuple ${t.id || '(no id)'} has unknown schema ${JSON.stringify(t.schema)} (known: ${TUPLE_SCHEMA})`);
  }
  for (const field of CORE_FIELDS) {
    if (!(field in t) || ((t[field] === null || t[field] === undefined) && !(field === 'value' && t.kind === 'decision' && t.lock === 'candidate'))) {
      throw new TupleError('missing_core_field', `tuple ${t.id || '(no id)'} missing core field: ${field}`);
    }
  }
  if (!KINDS.includes(t.kind)) throw new TupleError('unknown_kind', `tuple ${t.id} has unknown kind ${JSON.stringify(t.kind)}`);
  if (typeof t.id !== 'string' || !SLUG_RE.test(t.id)) {
    throw new TupleError('invalid_id', `tuple id is not a stable slug: ${JSON.stringify(t.id)}`);
  }
  if (!LOCK_RUNGS.includes(t.lock)) {
    throw new TupleError('unknown_lock_rung', `tuple ${t.id} has unknown lock rung ${JSON.stringify(t.lock)} (rungs: ${LOCK_RUNGS.join(', ')})`);
  }
  validateInterval(t.interval);
  if (!t.receipt || typeof t.receipt !== 'object') throw new TupleError('invalid_receipt', `tuple ${t.id} receipt is not a map`);
  for (const field of RECEIPT_FIELDS) {
    if (!(field in t.receipt)) throw new TupleError('invalid_receipt', `tuple ${t.id} receipt missing ${field}`);
  }
  if (t.kind === 'fact') {
    const v = t.value;
    if (!v || typeof v !== 'object' || !v.entity || !v.predicate || !('object' in v)) {
      throw new TupleError('invalid_value', `fact ${t.id} value needs entity, predicate, object`);
    }
  }
  if (t.kind === 'thread') {
    const v = t.value;
    if (!v || typeof v !== 'object' || !v.plant || !v.due) {
      throw new TupleError('invalid_value', `thread ${t.id} value needs plant and due (pay, release_reason optional)`);
    }
    if (!t.interval.scope) for (const coord of [v.plant, v.due, v.pay, ...(Array.isArray(v.uses) ? v.uses : [])].filter(Boolean)) parseCoord(coord);
  }
  if (t.kind === 'alias') {
    const v = t.value;
    if (!v || typeof v !== 'object' || !v.target || !Array.isArray(v.variants) || !v.variants.length) {
      throw new TupleError('invalid_value', `alias ${t.id} value needs target and variants`);
    }
  }
  if (t.kind === 'structural') {
    const v = t.value;
    if (!v || typeof v !== 'object' || !v.beat || !('position' in v)) {
      throw new TupleError('invalid_value', `structural ${t.id} value needs beat and position`);
    }
  }
  return t;
}

/** A tuple is locked-with-acceptance only when the acceptance receipt is present. */
export function hasAcceptance(t) {
  if (!t.accepted_by || !t.accepted_on) return false;
  // Pre-W6 receipt-bearing fixtures retain their schema-1 contract. Extracted
  // candidates and all new acceptances require a receipt bound to their content.
  if (!t.acceptance_receipt) return !t.receipt?.prompt_hash;
  const r = t.acceptance_receipt;
  return TRUTH_WRITERS.includes(r.writer) && r.accepted_by === 'john'
    && t.accepted_by === r.accepted_by && t.accepted_on === r.accepted_on
    && r.tuple_hash === acceptanceHash(t);
}

export const TRUTH_WRITERS = Object.freeze(['accept', 'lock']);
export function acceptanceHash(tuple) {
  // Bind authored content, not the index's recomputed dependency/cost fields.
  const content = canonicalTuple(tuple);
  for (const field of ['acceptance_receipt', 'deferred', 'depends_on', 'cost_of_change']) delete content[field];
  const stable = (v) => Array.isArray(v) ? v.map(stable) : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, stable(v[k])])) : v;
  return crypto.createHash('sha256').update(JSON.stringify(stable(content))).digest('hex');
}

export function hasMintedFields(t) {
  return (t.lock === 'locked' || ['allow_terms', 'accepted_by', 'accepted_on', 'acceptance_receipt'].some((k) => Object.hasOwn(t, k))) && !hasAcceptance(t);
}

/** allow_terms is honoured only on a locked decision with an acceptance receipt. */
export function effectiveAllowTerms(t) {
  if (t.kind === 'decision' && t.interval?.scope !== 'unspecified' && t.lock === 'locked' && hasAcceptance(t)) return t.allow_terms || [];
  return [];
}

// ---------------------------------------------------------------------------
// Sidecar ledger files: <file>.ledger.yaml beside each prose file.
//
// YAML without a dependency (the W1 gate pins mammoth as the ONLY shipped
// package): sidecars are EMITTED in the JSON subset of YAML 1.2 —
// deterministic, and any YAML reader parses it — and READ by trying JSON
// first, then a minimal block-YAML reader for hand-written sidecars
// (indented maps, `- ` sequences, plain/quoted scalars). Anything beyond
// that subset is refused as unreadable — refuse, never guess.
// ---------------------------------------------------------------------------

function parseScalar(text) {
  if (text === '' || text === 'null' || text === '~') return null;
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (text === '[]') return [];
  if (text === '{}') return {};
  if (text.startsWith('{') || text.startsWith('[')) return JSON.parse(text);
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
  if (text.length >= 2 && text.startsWith('"') && text.endsWith('"')) return JSON.parse(text);
  if (text.length >= 2 && text.startsWith("'") && text.endsWith("'")) return text.slice(1, -1).replace(/''/g, "'");
  return text;
}

function parseBlockNode(rows, i, minIndent) {
  if (i >= rows.length || rows[i].indent < minIndent) return [null, i];
  const indent = rows[i].indent;
  const isSeqRow = (row) => row.text === '-' || row.text.startsWith('- ');
  if (isSeqRow(rows[i])) {
    const out = [];
    while (i < rows.length && rows[i].indent === indent && isSeqRow(rows[i])) {
      if (rows[i].text !== '-') {
        // `- key: value` — the rest of the row is the item's first line.
        rows[i] = { indent: indent + 2, text: rows[i].text.slice(2).trim() };
      } else {
        i += 1;
      }
      const [value, next] = parseBlockNode(rows, i, indent + 1);
      out.push(value);
      i = next;
    }
    return [out, i];
  }
  const out = {};
  while (i < rows.length && rows[i].indent === indent && !isSeqRow(rows[i])) {
    const m = /^([^:]+):(?:\s+(.*))?$/.exec(rows[i].text);
    if (!m) throw new Error(`beyond the block subset: ${rows[i].text}`);
    const key = m[1].trim();
    i += 1;
    if (m[2] !== undefined && m[2].trim() !== '') {
      out[key] = parseScalar(m[2].trim());
    } else if (i < rows.length && rows[i].indent > indent) {
      const [value, next] = parseBlockNode(rows, i, indent + 1);
      out[key] = value;
      i = next;
    } else {
      out[key] = null;
    }
  }
  return [out, i];
}

function parseYamlSubset(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    /* not the JSON subset — block reader below */
  }
  const rows = [];
  for (const line of String(raw).split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith('#')) continue;
    rows.push({ indent: line.length - line.trimStart().length, text: stripped });
  }
  if (!rows.length) return null;
  const [value, next] = parseBlockNode(rows, 0, 0);
  if (next !== rows.length) throw new Error('trailing content beyond the block subset');
  return value;
}

export function sidecarPathFor(proseFile) {
  return `${proseFile}.ledger.yaml`;
}

export function emptySidecar() {
  return { schema: TUPLE_SCHEMA, tuples: [] };
}

/** Parse a sidecar; every tuple is validated; garbage YAML is refused. */
export function readSidecar(proseFile) {
  const file = sidecarPathFor(proseFile);
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (e) {
    if (e && e.code === 'ENOENT') return emptySidecar();
    throw new TupleError('sidecar_unreadable', `cannot read ${file}: ${e.message}`);
  }
  return parseSidecarText(raw);
}

/** The same reader validates a prepared insertion before its first durable write. */
export function parseSidecarText(raw) {
  let doc;
  try {
    doc = parseYamlSubset(raw);
  } catch {
    throw new TupleError('sidecar_unreadable', 'sidecar does not parse as YAML');
  }
  if (!doc || !Array.isArray(doc.tuples)) throw new TupleError('sidecar_unreadable', 'sidecar holds no tuples list');
  for (const t of doc.tuples) validateTuple(t);
  return doc;
}

function canonicalTuple(t) {
  const out = { id: t.id, kind: t.kind, schema: t.schema, value: t.value, interval: t.interval, lock: t.lock, receipt: t.receipt };
  for (const field of OPTIONAL_FIELDS) {
    if (field in t && t[field] !== undefined) out[field] = t[field];
  }
  return out;
}

/** Serialize a sidecar doc deterministically (tuples sorted by id, canonical field order). */
export function serializeSidecar(doc) {
  const tuples = [...doc.tuples].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map(canonicalTuple);
  return `${JSON.stringify({ schema: TUPLE_SCHEMA, tuples }, null, 2)}\n`;
}

/**
 * Write the sidecar beside its prose file — atomically, under the root lock.
 * Every tuple is validated first; the PROSE FILE IS NEVER TOUCHED (the only
 * write target this module ever has ends in .ledger.yaml).
 */
export function writeSidecar(proseFile, doc, stateDir, lockOpts) {
  for (const t of doc.tuples) validateTuple(t);
  const text = serializeSidecar(doc);
  return withLock(stateDir, lockOpts, () => atomicWriteFile(sidecarPathFor(proseFile), text));
}

/**
 * Add or update a tuple in a sidecar doc. A fact is validated against the
 * pack's CLOSED catalog first: an unknown predicate is a refusal and NO tuple
 * is written. An update never changes the id (the id is the match key).
 */
export function upsertTuple(doc, tuple, pack) {
  validateTuple(tuple);
  if (tuple.kind === 'fact' && pack) {
    const check = validateClaim(pack, tuple.value);
    if (!check.ok) return { ok: false, refusal: check.refusal, predicate: check.predicate };
  }
  const i = doc.tuples.findIndex((t) => t.id === tuple.id);
  if (i >= 0) doc.tuples[i] = tuple;
  else doc.tuples.push(tuple);
  return { ok: true, tuple };
}

// ---------------------------------------------------------------------------
// Stable ids: a rename is an alias entry, never an id change.
// ---------------------------------------------------------------------------

/** An id change is REFUSED — always. The rename path is recordRename. */
export function changeId() {
  throw new TupleError('id_change_refused', 'a rename is an alias entry, never an id change — record it with recordRename');
}

/**
 * Record an authorial rename as an alias entry on the target id. The target
 * tuple's id is untouched; the new surface becomes a variant, interval-scoped.
 */
export function recordRename(doc, { target, variant, interval, receipt, authorial_rename = true }) {
  const aliasId = `alias.${target}`;
  const existing = doc.tuples.find((t) => t.kind === 'alias' && t.id === aliasId);
  if (existing) {
    if (!existing.value.variants.includes(variant)) existing.value.variants.push(variant);
    if (authorial_rename) existing.authorial_rename = true;
    return existing;
  }
  const tuple = {
    id: aliasId,
    kind: 'alias',
    schema: TUPLE_SCHEMA,
    value: { target, variants: [variant] },
    interval,
    lock: 'candidate',
    receipt,
  };
  if (authorial_rename) tuple.authorial_rename = true;
  validateTuple(tuple);
  doc.tuples.push(tuple);
  return tuple;
}

// ---------------------------------------------------------------------------
// Receipts: {span, heading_path, line_hint, date}. Exact match stands; a
// fuzzy match becomes a receipt-drift record; the stored span never moves.
// ---------------------------------------------------------------------------

function foldForFuzz(text) {
  // Case-fold, drop punctuation, collapse whitespace — with a map back to
  // original offsets so a proposed anchor quotes the REAL prose.
  const chars = [];
  const map = [];
  let lastWasSpace = true;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (/\s/.test(c)) {
      if (!lastWasSpace) {
        chars.push(' ');
        map.push(i);
        lastWasSpace = true;
      }
    } else if (/[\p{L}\p{N}]/u.test(c)) {
      chars.push(c.toLowerCase());
      map.push(i);
      lastWasSpace = false;
    }
  }
  return { folded: chars.join(''), map };
}

function lineHintAt(text, offset) {
  let line = 1;
  for (let i = 0; i < offset && i < text.length; i++) if (text[i] === '\n') line++;
  return line;
}

/**
 * Resolve a receipt against the CURRENT prose text.
 *  - exact span found        → { status: 'exact' } — the receipt stands.
 *  - fuzzy match only        → { status: 'drift', drift: { proposed } } — the
 *    stored span is UNCHANGED; re-anchoring happens only at accept.
 *  - no match                → { status: 'unanchored' }.
 * This function never mutates the tuple and never writes anything.
 */
export function resolveReceipt(proseText, receipt) {
  if (proseText.includes(receipt.span)) {
    return { status: 'exact', stored: receipt };
  }
  const text = foldForFuzz(proseText);
  const span = foldForFuzz(receipt.span);
  if (span.folded.length) {
    const at = text.folded.indexOf(span.folded);
    if (at >= 0) {
      const start = text.map[at];
      const end = text.map[at + span.folded.length - 1] + 1;
      return {
        status: 'drift',
        stored: receipt,
        drift: {
          kind: 'receipt-drift',
          proposed: {
            span: proseText.slice(start, end),
            heading_path: receipt.heading_path,
            line_hint: lineHintAt(proseText, start),
          },
        },
      };
    }
  }
  return { status: 'unanchored', stored: receipt };
}

/**
 * The ONLY re-anchoring path: at accept. Applies a drift proposal to the
 * tuple's receipt and records the acceptance receipt on the tuple.
 */
export function reanchorAtAccept(doc, tupleId, proposed, { accepted_by, accepted_on }) {
  if (!accepted_by || !accepted_on) {
    throw new TupleError('acceptance_required', 're-anchoring happens only at accept: accepted_by and accepted_on required');
  }
  const t = doc.tuples.find((x) => x.id === tupleId);
  if (!t) throw new TupleError('unknown_id', `no tuple ${tupleId}`);
  t.receipt = { ...t.receipt, span: proposed.span, line_hint: proposed.line_hint };
  if (proposed.heading_path) t.receipt.heading_path = proposed.heading_path;
  t.accepted_by = accepted_by;
  t.accepted_on = accepted_on;
  return t;
}

// ---------------------------------------------------------------------------
// Alias trie: case-folded over alias entries and variants, surface string →
// id within an interval. A miss is an unknown_noun, never an assertion.
// ---------------------------------------------------------------------------

function trieNode() {
  return { children: new Map(), entries: [] };
}

/** Build a character trie over every alias variant (case-folded). */
export function buildAliasTrie(tuples) {
  const root = trieNode();
  for (const t of tuples) {
    if (t.kind !== 'alias') continue;
    for (const variant of t.value.variants) {
      let node = root;
      for (const c of variant.toLowerCase()) {
        if (!node.children.has(c)) node.children.set(c, trieNode());
        node = node.children.get(c);
      }
      node.entries.push({ target: t.value.target, interval: t.interval });
    }
  }
  return root;
}

/**
 * Resolve a surface string to an id within story time. Scope: a {coord}
 * must lie inside the alias interval; an {interval} must overlap it.
 * Every miss — unknown surface, or known surface out of scope — is
 * { unknown_noun: surface }, never an assertion and never a throw.
 */
export function resolveSurface(trie, surface, scope = {}) {
  let node = trie;
  for (const c of String(surface).toLowerCase()) {
    node = node.children.get(c);
    if (!node) return { unknown_noun: surface };
  }
  const hits = node.entries.filter((e) => {
    // Reading a proposed identity may retain unknown chronology. Ordinary
    // time-scoped alias resolution keeps its original refusal behavior.
    if (e.interval.scope === 'unspecified') return scope.includeUnspecified === true;
    if (scope.coord) return intervalContainsCoord(e.interval, scope.coord);
    if (scope.interval) return intervalOverlaps(e.interval, scope.interval);
    return true;
  });
  if (!hits.length) return { unknown_noun: surface };
  const targets = [...new Set(hits.map((h) => h.target))].sort();
  if (scope.includeHits) return { hits, ...(targets.length === 1 ? { id: targets[0] } : { unknown_noun: surface }) };
  return { id: targets[0] };
}

/** Entity ids named inside a span (word by word), scoped to an interval. */
export function namedEntitiesInSpan(trie, span, interval) {
  const ids = new Set();
  for (const word of String(span).split(/[^\p{L}\p{N}'_-]+/u)) {
    if (!word) continue;
    const hit = resolveSurface(trie, word, interval ? { interval } : {});
    if (hit.id) ids.add(hit.id);
  }
  return [...ids].sort();
}

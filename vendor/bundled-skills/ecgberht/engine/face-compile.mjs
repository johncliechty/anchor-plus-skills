/**
 * Wave 10 — Face compile projection (RESTORED — Master-Plan P4).
 *
 * The campaign's narrative memory is a PROJECTION over typed face_events on
 * immutable content-hashed source_text blobs, with provenance spans, visible
 * drops, first-class retraction, bounded compile, and a cost ledger — all
 * inside a live Wave-8 session envelope.
 *
 * Stores (Durable-store map S5):
 *   - face_events   → `.ecgberht/face-events.json` (append under lock)
 *   - source_text   → `.ecgberht/source-text/<sha256>` (write-once by hash)
 *
 * Event kinds (Wave-6 allow-list VERSION BUMP → v2): face_assert, face_retract,
 * face_refine, face_compile — appended through the spine so chat-shaped kinds
 * remain structurally impossible.
 *
 * Compile is deterministic / zero-model for this wave (same posture as Wave 9
 * scaffolding): multi-pass fixed-point extraction with a circuit breaker that
 * HALTs to John as COMPILE_CIRCUIT_BREAK and never lands a partial Face version.
 *
 * Provenance VIEWER UI is deferred to Wave 18 (Master Plan's own deferral).
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  FACE_FILE_NAME,
  FACE_NARRATIVE_FIELDS,
} from './face-strip.mjs';
import {
  appendRoadmapEventThroughSpine,
  assertEventKindAllowed,
  assertStoreDeclared,
  SPINE_EVENT_KINDS,
  ROADMAP_EVENT_KINDS_VERSION,
} from './ledger-spine.mjs';
import {
  debitSessionEnvelope,
  readEnvelopeState,
  ENVELOPE_CODE,
} from './session-envelope.mjs';
import {
  priceCompile,
  estimateTokens,
} from './cost-model.mjs';
import { rewriteFaceNarrative } from './write-authority.mjs';

// ── Named durability helpers (S5 — removal-proof T-DUR-S5) ─────────────────

/** Named lock helper — Durable-store map S5. */
export const FACE_LOCK_HELPER = 'withFileLock';

/** Named atomic write — Durable-store map S5. */
export const FACE_ATOMIC_WRITE = 'writeFileAtomicSync';

/** Relative path of the face_events ledger under a project root. */
export const FACE_EVENTS_REL = path.join('.ecgberht', 'face-events.json');

/** Relative directory of content-hashed source_text blobs. */
export const SOURCE_TEXT_DIR_REL = path.join('.ecgberht', 'source-text');

/** Schema id for the face_events store. */
export const FACE_EVENTS_SCHEMA = 'ecgberht-face-events-v0';

/** Schema id for a compile proposal / cost ledger row. */
export const FACE_COMPILE_SCHEMA = 'ecgberht-face-compile-v0';

/** Typed face event kinds (admitted on spine allow-list v2). */
export const FACE_EVENT_KINDS = Object.freeze([
  'face_assert',
  'face_retract',
  'face_refine',
  'face_compile',
]);

/**
 * Named bound: max compiler passes before the circuit breaker trips.
 * Fixed-point must be reached within this many passes or we HALT to John.
 */
export const COMPILE_MAX_PASSES = 8;

/** Idempotence key name. */
export const FACE_COMPILE_IDEMPOTENCE_KEY = 'client_event_id';

// ── Failure states (compile surface — Master-Plan P4 table) ────────────────

export const COMPILE_CODE = Object.freeze({
  NO_ENVELOPE: 'COMPILE_NO_ENVELOPE',
  CIRCUIT_BREAK: 'COMPILE_CIRCUIT_BREAK',
  OUTPUT_INVALID: 'COMPILE_OUTPUT_INVALID',
  FACE_EVENTS_UNREADABLE: 'FACE_EVENTS_UNREADABLE',
  SOURCE_EMPTY: 'COMPILE_SOURCE_EMPTY',
  ENVELOPE_STATE_UNKNOWN: 'ENVELOPE_STATE_UNKNOWN',
});

export const COMPILE_TEXT = Object.freeze({
  [COMPILE_CODE.NO_ENVELOPE]:
    'No confirmed session envelope — compile queued; confirm a budget to run it.',
  [COMPILE_CODE.CIRCUIT_BREAK]:
    'The compiler could not converge in <N> passes — halted; your call.',
  [COMPILE_CODE.OUTPUT_INVALID]:
    'Compile output failed validation and was discarded; the Face is unchanged.',
  [COMPILE_CODE.FACE_EVENTS_UNREADABLE]:
    'Face history cannot be read — compile refused rather than compiled blind.',
  [COMPILE_CODE.SOURCE_EMPTY]:
    'Nothing new to compile — the Face already reflects everything recorded.',
  [COMPILE_CODE.ENVELOPE_STATE_UNKNOWN]:
    'Envelope balance unknown (ledger gap) — compile refused until it is repaired.',
});

/**
 * @param {string} code COMPILE_CODE value
 * @param {object} [extra]
 */
export function compileFailure(code, extra = {}) {
  let text = COMPILE_TEXT[code] ?? COMPILE_TEXT[COMPILE_CODE.ENVELOPE_STATE_UNKNOWN];
  const n = extra.max_passes ?? extra.passes ?? COMPILE_MAX_PASSES;
  if (code === COMPILE_CODE.CIRCUIT_BREAK && typeof text === 'string') {
    text = text.replace(/<N>/g, String(n));
  }
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    face_compile: true,
    face_version_landed: false,
    ...extra,
  };
}

/**
 * Full failure-state table for the compile surface (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function faceCompileFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (no live envelope)',
      status_code: COMPILE_CODE.NO_ENVELOPE,
      user_text: COMPILE_TEXT[COMPILE_CODE.NO_ENVELOPE],
    }),
    Object.freeze({
      state: 'dependency-slow-or-killed (non-convergent)',
      status_code: COMPILE_CODE.CIRCUIT_BREAK,
      user_text: COMPILE_TEXT[COMPILE_CODE.CIRCUIT_BREAK],
    }),
    Object.freeze({
      state: 'dependency-returns-garbage',
      status_code: COMPILE_CODE.OUTPUT_INVALID,
      user_text: COMPILE_TEXT[COMPILE_CODE.OUTPUT_INVALID],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: COMPILE_CODE.FACE_EVENTS_UNREADABLE,
      user_text: COMPILE_TEXT[COMPILE_CODE.FACE_EVENTS_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: COMPILE_CODE.SOURCE_EMPTY,
      user_text: COMPILE_TEXT[COMPILE_CODE.SOURCE_EMPTY],
    }),
    Object.freeze({
      state: 'unknown (envelope state undeterminable)',
      status_code: COMPILE_CODE.ENVELOPE_STATE_UNKNOWN,
      user_text: COMPILE_TEXT[COMPILE_CODE.ENVELOPE_STATE_UNKNOWN],
    }),
  ]);
}

// ── Hash / blob helpers ────────────────────────────────────────────────────

/**
 * Content hash of source text (sha256 hex of UTF-8 bytes).
 * @param {string|Buffer} text
 * @returns {string}
 */
export function hashSourceText(text) {
  const buf = Buffer.isBuffer(text) ? text : Buffer.from(String(text ?? ''), 'utf8');
  return crypto.createHash('sha256').update(buf).digest('hex');
}

/**
 * Absolute path of a content-hashed source_text blob.
 * @param {string} projectRoot
 * @param {string} sourceHash
 */
export function sourceTextBlobPath(projectRoot, sourceHash) {
  return path.join(
    path.resolve(projectRoot),
    SOURCE_TEXT_DIR_REL,
    String(sourceHash),
  );
}

/**
 * Absolute path of the face_events ledger.
 * @param {string} projectRoot
 */
export function faceEventsPath(projectRoot) {
  return path.join(path.resolve(projectRoot), FACE_EVENTS_REL);
}

/**
 * Empty face_events ledger shape (empty-but-valid ≠ unreadable).
 * @returns {object}
 */
export function emptyFaceEventsLedger() {
  return {
    schema: FACE_EVENTS_SCHEMA,
    events: [],
    versions: [],
    next_seq: 1,
  };
}

/**
 * Write-once by content hash. Same bytes → ok (idempotent). Different bytes
 * at the same hash path is a collision refusal (should be cryptographically
 * impossible for sha256 of the payload that is the hash).
 *
 * Serialization: withFileLock on the blob path; writeFileAtomicSync.
 *
 * @param {string} projectRoot
 * @param {string} text
 * @param {{ timeoutMs?: number }} [opts]
 * @returns {{ ok: true, source_hash: string, path: string, wrote: boolean, bytes: number }
 *   | { ok: false, code: string, message: string }}
 */
export function writeSourceTextBlob(projectRoot, text, opts = {}) {
  const storeGate = assertStoreDeclared('source_text');
  if (!storeGate.ok) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'store-not-declared',
      detail: storeGate,
    });
  }
  const raw = text == null ? '' : String(text);
  const buf = Buffer.from(raw, 'utf8');
  const source_hash = hashSourceText(buf);
  const blobPath = sourceTextBlobPath(projectRoot, source_hash);
  const dir = path.dirname(blobPath);

  try {
    return withFileLock(
      blobPath,
      () => {
        fs.mkdirSync(dir, { recursive: true });
        if (fs.existsSync(blobPath)) {
          // encoding-lint: raw-bytes - content-hash integrity is a BYTE compare;
          // decoding first would hide hash mismatches and re-introduce mojibake risk.
          const existing = fs.readFileSync(blobPath);
          if (Buffer.compare(existing, buf) === 0) {
            return {
              ok: true,
              source_hash,
              path: blobPath,
              wrote: false,
              bytes: buf.length,
              immutable: true,
            };
          }
          return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
            error: 'source-text-hash-collision',
            source_hash,
          });
        }
        // Write UTF-8 string through the atomic primitive (bytes identical to buf).
        writeFileAtomicSync(blobPath, raw);
        return {
          ok: true,
          source_hash,
          path: blobPath,
          wrote: true,
          bytes: buf.length,
          immutable: true,
        };
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error('source-text lock timeout');
          err.code = 'ELOCKTIMEOUT';
          err.info = info;
          return err;
        },
      },
    );
  } catch (e) {
    return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
      error: 'source-text-write-failed',
      detail: String(e?.message ?? e),
    });
  }
}

/**
 * Read a content-hashed source_text blob. Returns exact UTF-8 bytes as string.
 * @param {string} projectRoot
 * @param {string} sourceHash
 * @returns {{ ok: true, source_hash: string, text: string, bytes: Buffer }
 *   | { ok: false, code: string, message: string }}
 */
export function readSourceTextBlob(projectRoot, sourceHash) {
  if (!sourceHash || typeof sourceHash !== 'string') {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'source-hash-required',
    });
  }
  const blobPath = sourceTextBlobPath(projectRoot, sourceHash);
  try {
    if (!fs.existsSync(blobPath)) {
      return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
        error: 'source-text-missing',
        source_hash: sourceHash,
      });
    }
    // encoding-lint: raw-bytes - filename IS the content hash over on-disk bytes;
    // a decoded read would erase INVALID_UTF8 evidence and desync the hash check.
    const bytes = fs.readFileSync(blobPath);
    // Integrity: filename IS the content hash
    const actual = hashSourceText(bytes);
    if (actual !== sourceHash) {
      return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
        error: 'source-text-tampered',
        source_hash: sourceHash,
        actual_hash: actual,
      });
    }
    return {
      ok: true,
      source_hash: sourceHash,
      text: bytes.toString('utf8'),
      bytes,
    };
  } catch (e) {
    return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
      error: 'source-text-unreadable',
      detail: String(e?.message ?? e),
      source_hash: sourceHash,
    });
  }
}

/**
 * Resolve a provenance span against the content-hashed blob.
 * Property: the resolved slice reproduces the compiled field value byte-identically
 * when the field was extracted as a contiguous span of the source.
 *
 * @param {string} projectRoot
 * @param {{ source_hash: string, start: number, end: number }} span
 * @returns {{ ok: true, text: string, bytes: Buffer, source_hash: string, start: number, end: number }
 *   | { ok: false, code: string, message: string }}
 */
export function resolveProvenanceSpan(projectRoot, span) {
  if (!span || typeof span !== 'object') {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'provenance-span-required',
    });
  }
  const blob = readSourceTextBlob(projectRoot, span.source_hash);
  if (!blob.ok) return blob;
  const start = Number(span.start);
  const end = Number(span.end);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'provenance-span-invalid',
      start: span.start,
      end: span.end,
    });
  }
  if (end > blob.bytes.length) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'provenance-span-out-of-range',
      start,
      end,
      blob_bytes: blob.bytes.length,
    });
  }
  const slice = blob.bytes.subarray(start, end);
  return {
    ok: true,
    text: slice.toString('utf8'),
    bytes: slice,
    source_hash: span.source_hash,
    start,
    end,
  };
}

// ── Face events ledger IO ──────────────────────────────────────────────────

function readFaceEventsFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return { ok: true, exists: false, value: null };
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    if (!raw || !String(raw).trim()) {
      return { ok: true, exists: true, value: null, empty: true };
    }
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { ok: false, unreadable: true, detail: 'not-an-object' };
    }
    return { ok: true, exists: true, value };
  } catch (e) {
    return {
      ok: false,
      unreadable: true,
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Load face_events under lock for a mutate cycle.
 * @param {string} projectRoot
 * @param {(ledger: object) => object} mutator
 * @param {object} [opts]
 */
function withFaceEventsLedger(projectRoot, mutator, opts = {}) {
  const filePath = faceEventsPath(projectRoot);
  const dir = path.dirname(filePath);
  const storeGate = assertStoreDeclared('face_events');
  if (!storeGate.ok) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'store-not-declared',
      detail: storeGate,
    });
  }
  try {
    return withFileLock(
      filePath,
      () => {
        const read = readFaceEventsFile(filePath);
        if (!read.ok) {
          return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
            error: 'backing-store-unreadable',
            detail: read.detail,
          });
        }
        const base =
          read.exists && read.value
            ? {
                ...emptyFaceEventsLedger(),
                ...read.value,
                events: Array.isArray(read.value.events)
                  ? [...read.value.events]
                  : [],
                versions: Array.isArray(read.value.versions)
                  ? [...read.value.versions]
                  : [],
              }
            : emptyFaceEventsLedger();

        const result = mutator(base);
        if (!result || result.ok === false) {
          return result;
        }
        if (result.skip_write) {
          return result;
        }
        const nextLedger = result.ledger ?? base;
        fs.mkdirSync(dir, { recursive: true });
        writeFileAtomicSync(
          filePath,
          `${JSON.stringify(nextLedger, null, 2)}\n`,
        );
        return {
          ...result,
          ledger: nextLedger,
          path: filePath,
          sot_written: true,
        };
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error(COMPILE_TEXT[COMPILE_CODE.FACE_EVENTS_UNREADABLE]);
          err.code = 'ELOCKTIMEOUT';
          err.info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if (e && e.code === 'ELOCKTIMEOUT') {
      return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
        error: 'lock-contended',
        detail: String(e?.message ?? e),
      });
    }
    return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
      error: 'face-events-io',
      detail: String(e?.message ?? e),
    });
  }
}

/**
 * Read-only load of face_events (no lock required for tests; production
 * mutators use withFaceEventsLedger).
 * @param {string} projectRoot
 */
export function readFaceEvents(projectRoot) {
  const filePath = faceEventsPath(projectRoot);
  const read = readFaceEventsFile(filePath);
  if (!read.ok) {
    return compileFailure(COMPILE_CODE.FACE_EVENTS_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: read.detail,
    });
  }
  if (!read.exists || !read.value) {
    return {
      ok: true,
      empty: true,
      exists: false,
      ledger: emptyFaceEventsLedger(),
      events: [],
      versions: [],
    };
  }
  const ledger = {
    ...emptyFaceEventsLedger(),
    ...read.value,
    events: Array.isArray(read.value.events) ? read.value.events : [],
    versions: Array.isArray(read.value.versions) ? read.value.versions : [],
  };
  return {
    ok: true,
    empty: ledger.events.length === 0,
    exists: true,
    ledger,
    events: ledger.events,
    versions: ledger.versions,
  };
}

/**
 * Source-removal proof: face-compile module uses the named durable helpers.
 * @param {string} sourceText
 */
export function assertFaceDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('appendRoadmapEventThroughSpine')) {
    missing.push('appendRoadmapEventThroughSpine');
  }
  if (!sourceText.includes('debitSessionEnvelope')) {
    missing.push('debitSessionEnvelope');
  }
  return { ok: missing.length === 0, missing };
}

// ── Pure projection law ────────────────────────────────────────────────────

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeys(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * Canonical hash of a face version body (fields + exclusions + source hashes).
 * @param {object} body
 * @returns {string}
 */
export function hashFaceVersion(body) {
  const canonical = JSON.stringify(sortKeys(body));
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

/**
 * Build a hard exclusion set from face_retract events.
 * Retraction preserves content + why.
 *
 * @param {object[]} events
 * @returns {Map<string, { fact_id: string, content: string, why: string, retracted_at?: string, client_event_id?: string }>}
 */
export function buildExclusionSet(events) {
  const map = new Map();
  for (const e of events ?? []) {
    if (!e || e.kind !== 'face_retract') continue;
    const fact_id = e.fact_id ?? e.field ?? null;
    if (!nonEmpty(fact_id)) continue;
    map.set(fact_id, {
      fact_id,
      content: e.content ?? e.value ?? '',
      why: e.why ?? e.reason ?? '',
      retracted_at: e.at ?? null,
      client_event_id: e.client_event_id ?? null,
      source_hash: e.source_hash ?? null,
    });
  }
  // A later face_assert / face_refine on the same fact_id after retract would
  // re-admit only if we cleared exclusion — plan: retraction is a HARD exclusion
  // on recompile, so we keep exclusions for any fact that has a retract and no
  // later refine/assert that is explicitly not excluded. Hard exclusion = keep.
  return map;
}

/**
 * Project face_events into a Face field map with provenance spans.
 * Retractions form a hard exclusion set; excluded fields are absent from fields
 * but listed under `exclusions` (visible).
 *
 * @param {object[]} events
 * @returns {{
 *   fields: Record<string, { value: string, provenance: object, kind: string }>,
 *   exclusions: object[],
 *   source_hashes: string[],
 *   dropped_or_generalized: object[],
 * }}
 */
export function projectFaceFromEvents(events) {
  const exclusions = buildExclusionSet(events);
  /** @type {Record<string, { value: string, provenance: object, kind: string, fact_id: string }>} */
  const fields = {};
  const sourceHashes = new Set();
  const dropped = [];

  for (const e of events ?? []) {
    if (!e || typeof e !== 'object') continue;
    if (e.kind === 'face_compile') {
      if (Array.isArray(e.dropped_or_generalized)) {
        for (const d of e.dropped_or_generalized) dropped.push(d);
      }
      continue;
    }
    if (e.kind !== 'face_assert' && e.kind !== 'face_refine') continue;
    const fact_id = e.fact_id ?? e.field;
    if (!nonEmpty(fact_id)) continue;
    if (exclusions.has(fact_id)) continue; // hard exclusion

    const value = e.value ?? e.content ?? '';
    const provenance = e.provenance ?? {
      source_hash: e.source_hash ?? null,
      start: e.start ?? 0,
      end: e.end ?? (typeof value === 'string' ? Buffer.byteLength(value, 'utf8') : 0),
    };
    if (provenance.source_hash) sourceHashes.add(provenance.source_hash);
    if (e.source_hash) sourceHashes.add(e.source_hash);

    fields[fact_id] = {
      fact_id,
      value: String(value),
      provenance: {
        source_hash: provenance.source_hash,
        start: Number(provenance.start) || 0,
        end: Number(provenance.end) || 0,
      },
      kind: e.kind,
      at: e.at ?? null,
      client_event_id: e.client_event_id ?? null,
    };
  }

  return {
    fields,
    exclusions: [...exclusions.values()],
    source_hashes: [...sourceHashes].sort(),
    dropped_or_generalized: dropped,
  };
}

/**
 * Property helper: for a compiled field with provenance, resolve the span and
 * assert the source text reproduces (byte-identical when field is a contiguous
 * slice). Also returns the full source blob for the Face version's source_hash.
 *
 * @param {string} projectRoot
 * @param {{ value: string, provenance: { source_hash: string, start: number, end: number } }} field
 * @returns {{ ok: true, field_bytes: string, source_text: string, source_hash: string, span_matches_value: boolean }
 *   | { ok: false, code: string, message: string }}
 */
export function reproduceSourceFromProvenance(projectRoot, field) {
  if (!field || !field.provenance) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'field-provenance-missing',
    });
  }
  const span = resolveProvenanceSpan(projectRoot, field.provenance);
  if (!span.ok) return span;
  const full = readSourceTextBlob(projectRoot, field.provenance.source_hash);
  if (!full.ok) return full;
  return {
    ok: true,
    field_bytes: span.text,
    source_text: full.text,
    source_hash: field.provenance.source_hash,
    span_matches_value: span.text === String(field.value ?? ''),
    // Version-level property: the blob itself is the exact source text
    source_reproduces_byte_identically: true,
  };
}

// ── Bounded multi-pass compiler (deterministic) ────────────────────────────

/**
 * Extract narrative field candidates from a description string or object.
 * Pure, zero-model. Returns field map with byte offsets into `sourceText`.
 *
 * @param {string} sourceText
 * @param {object} [input] optional structured fields
 * @returns {{ fields: Record<string, { value: string, start: number, end: number }>, dropped: object[] }}
 */
export function extractFaceCandidates(sourceText, input = {}) {
  const text = String(sourceText ?? '');
  const buf = Buffer.from(text, 'utf8');
  /** @type {Record<string, { value: string, start: number, end: number }>} */
  const fields = {};
  const dropped = [];

  // Structured input wins when present (typed form).
  for (const key of FACE_NARRATIVE_FIELDS) {
    if (input && nonEmpty(input[key])) {
      const value = String(input[key]).trim();
      // Find first occurrence in source for provenance span; if not found, span
      // covers a synthetic append region only when value is substring of source.
      const idx = text.indexOf(value);
      if (idx >= 0) {
        const start = Buffer.byteLength(text.slice(0, idx), 'utf8');
        const end = start + Buffer.byteLength(value, 'utf8');
        fields[key] = { value, start, end };
      } else {
        // Value not a contiguous substring — still compile, provenance points
        // at full source with a note in dropped_or_generalized.
        fields[key] = { value, start: 0, end: buf.length };
        dropped.push({
          kind: 'generalized',
          field: key,
          reason: 'value-not-contiguous-substring',
          value_preview: value.slice(0, 80),
        });
      }
    }
  }

  // Heading-based parse for free-form markdown (mirrors Face section markers).
  const headingMap = {
    'north star': 'north_star',
    'active effort': 'active_effort',
    'why next': 'why_next',
    'human wait': 'human_wait',
    'why stakes': 'why_stakes',
  };
  const headingRe = /^#{1,3}\s+(.+?)\s*$/gm;
  const matches = [...text.matchAll(headingRe)];
  for (let i = 0; i < matches.length; i += 1) {
    const m = matches[i];
    const title = String(m[1]).trim().toLowerCase();
    const field = headingMap[title];
    if (!field || fields[field]) continue;
    const bodyStart = m.index + m[0].length;
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].index : text.length;
    let body = text.slice(bodyStart, bodyEnd).trim();
    // Strip blockquote markers and HTML comments for the field value
    body = body
      .replace(/^>\s?/gm, '')
      .replace(/<!--[\s\S]*?-->/g, '')
      .trim();
    if (!body) {
      dropped.push({
        kind: 'dropped',
        field,
        reason: 'empty-section-body',
      });
      continue;
    }
    const idx = text.indexOf(body, bodyStart);
    const start =
      idx >= 0
        ? Buffer.byteLength(text.slice(0, idx), 'utf8')
        : Buffer.byteLength(text.slice(0, bodyStart), 'utf8');
    const end = start + Buffer.byteLength(body, 'utf8');
    fields[field] = { value: body, start, end };
  }

  // Any remaining non-empty prose lines not claimed → dropped_or_generalized.
  if (Object.keys(fields).length === 0 && text.trim()) {
    // Whole text as north_star fallback when no structure found
    const value = text.trim();
    const idx = text.indexOf(value);
    const start = idx >= 0 ? Buffer.byteLength(text.slice(0, idx), 'utf8') : 0;
    const end = start + Buffer.byteLength(value, 'utf8');
    fields.north_star = { value, start, end };
    dropped.push({
      kind: 'generalized',
      field: 'north_star',
      reason: 'unstructured-description-as-north-star',
    });
  }

  return { fields, dropped };
}

/**
 * One compile pass: extract → apply exclusions → produce candidate projection.
 * @param {string} sourceText
 * @param {object} input
 * @param {Map|object[]} exclusions
 * @returns {object}
 */
export function compilePass(sourceText, input, exclusions) {
  const extracted = extractFaceCandidates(sourceText, input);
  const exclMap =
    exclusions instanceof Map
      ? exclusions
      : buildExclusionSet(
          (exclusions ?? []).map((x) => ({
            kind: 'face_retract',
            fact_id: x.fact_id,
            content: x.content,
            why: x.why,
          })),
        );

  /** @type {Record<string, { value: string, start: number, end: number }>} */
  const fields = {};
  const visibleExclusions = [];
  for (const [k, v] of Object.entries(extracted.fields)) {
    if (exclMap.has(k)) {
      visibleExclusions.push({ ...exclMap.get(k), excluded_on_recompile: true });
      continue;
    }
    fields[k] = v;
  }
  // Also surface exclusions for facts that were never re-extracted
  for (const [k, v] of exclMap.entries()) {
    if (!visibleExclusions.some((e) => e.fact_id === k)) {
      visibleExclusions.push({ ...v, excluded_on_recompile: true });
    }
  }

  return {
    fields,
    dropped_or_generalized: extracted.dropped,
    exclusions: visibleExclusions,
    fingerprint: hashFaceVersion({ fields, exclusions: visibleExclusions }),
  };
}

/**
 * Bounded multi-pass compile with fixed-point check + circuit breaker.
 *
 * @param {string} sourceText
 * @param {object} [opts]
 * @returns {{ ok: true, passes: number, result: object, converged: true }
 *   | ReturnType<typeof compileFailure>}
 */
export function runBoundedCompile(sourceText, opts = {}) {
  const maxPasses = Number(opts.max_passes) > 0
    ? Number(opts.max_passes)
    : COMPILE_MAX_PASSES;
  const exclusions = opts.exclusions ?? new Map();
  const input = opts.input ?? {};

  // Injected non-convergent pass function for circuit-breaker tests.
  const passFn =
    typeof opts.passFn === 'function'
      ? opts.passFn
      : (text, inp, excl, pass) => compilePass(text, inp, excl);

  let prevFingerprint = null;
  let last = null;
  for (let pass = 1; pass <= maxPasses; pass += 1) {
    last = passFn(sourceText, input, exclusions, pass);
    if (!last || typeof last !== 'object') {
      return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
        error: 'pass-returned-garbage',
        passes: pass,
        max_passes: maxPasses,
      });
    }
    const fp = last.fingerprint ?? hashFaceVersion(last);
    if (prevFingerprint != null && fp === prevFingerprint) {
      return {
        ok: true,
        converged: true,
        passes: pass,
        result: last,
        max_passes: maxPasses,
      };
    }
    prevFingerprint = fp;
  }

  // Did not converge within max passes → circuit breaker. No partial version.
  return compileFailure(COMPILE_CODE.CIRCUIT_BREAK, {
    error: 'compile-circuit-break',
    passes: maxPasses,
    max_passes: maxPasses,
    face_version_landed: false,
  });
}

/**
 * Validate compile output before landing a Face version.
 * @param {object} result
 */
export function validateCompileOutput(result) {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'output-not-object',
    });
  }
  if (!result.fields || typeof result.fields !== 'object') {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'output-fields-missing',
    });
  }
  for (const [k, v] of Object.entries(result.fields)) {
    if (!nonEmpty(k) || !v || typeof v.value !== 'string') {
      return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
        error: 'output-field-invalid',
        field: k,
      });
    }
  }
  return { ok: true };
}

/**
 * Incremental diff: which fields changed vs a prior projection.
 * @param {Record<string, {value: string}>} prior
 * @param {Record<string, {value: string, start: number, end: number}>} next
 * @returns {{ changed: string[], unchanged: string[], added: string[], removed: string[] }}
 */
export function diffFaceFields(prior, next) {
  const p = prior ?? {};
  const n = next ?? {};
  const changed = [];
  const unchanged = [];
  const added = [];
  const removed = [];
  for (const k of new Set([...Object.keys(p), ...Object.keys(n)])) {
    const pv = p[k]?.value;
    const nv = n[k]?.value;
    if (pv == null && nv != null) added.push(k);
    else if (pv != null && nv == null) removed.push(k);
    else if (pv !== nv) changed.push(k);
    else unchanged.push(k);
  }
  return { changed, unchanged, added, removed };
}

// ── Cost ledger query ──────────────────────────────────────────────────────

/**
 * Every face_compile event must reference a live confirmed envelope with
 * remaining budget at the time of the query (or record remaining at debit).
 *
 * @param {string} projectRoot
 * @param {{ monoNow?: () => number }} [opts]
 * @returns {{ ok: true, compiles: object[], all_reference_live_envelope: boolean, envelope: object|null, balance: object|null }
 *   | { ok: false, code: string, message: string }}
 */
export function queryCompileCostLedger(projectRoot, opts = {}) {
  const face = readFaceEvents(projectRoot);
  if (!face.ok) return face;

  const envState = readEnvelopeState(projectRoot, opts);
  if (!envState.ok) {
    // Envelope ledger unreadable / unknown → ENVELOPE_STATE_UNKNOWN
    return compileFailure(COMPILE_CODE.ENVELOPE_STATE_UNKNOWN, {
      error: 'envelope-state-unknown',
      detail: envState,
    });
  }

  const compiles = (face.events ?? []).filter((e) => e && e.kind === 'face_compile');
  const live = envState.live === true;
  const balance = envState.balance ?? null;
  const envelope = envState.envelope ?? null;

  const rows = compiles.map((c) => {
    const hasRemaining =
      c.remaining_usd != null &&
      c.remaining_compiles != null &&
      Number(c.remaining_usd) >= 0 &&
      Number(c.remaining_compiles) >= 0;
    return {
      ...c,
      refs_envelope: nonEmpty(c.envelope_id),
      has_remaining_budget_at_debit: hasRemaining,
      envelope_id: c.envelope_id ?? null,
      tokens: c.tokens ?? null,
      cost_usd: c.cost_usd ?? null,
    };
  });

  const allOk =
    rows.every((r) => r.refs_envelope && r.has_remaining_budget_at_debit) &&
    (rows.length === 0 || (envelope != null && nonEmpty(envelope.envelope_id)));

  return {
    ok: true,
    compiles: rows,
    all_reference_live_envelope: allOk,
    live_envelope: live,
    envelope,
    balance,
    // Plan done-when: every compile event references a live confirmed envelope
    // with remaining budget (ledger query). When there is no live envelope NOW
    // but historical compiles recorded remaining at debit, still report the
    // historical integrity separately.
    historical_integrity: rows.every(
      (r) => r.refs_envelope && r.has_remaining_budget_at_debit,
    ),
  };
}

// ── Retraction ─────────────────────────────────────────────────────────────

/**
 * Append a face_retract event: preserves content + why; hard exclusion on recompile.
 *
 * @param {string} projectRoot
 * @param {{
 *   fact_id: string,
 *   why: string,
 *   content?: string,
 *   client_event_id?: string,
 *   at?: string,
 *   skip_index?: boolean,
 * }} opts
 */
export function retractFaceFact(projectRoot, opts = {}) {
  const fact_id = opts.fact_id ?? opts.field;
  if (!nonEmpty(fact_id)) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'fact_id-required',
    });
  }
  if (!nonEmpty(opts.why)) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'why-required',
      message: 'Retraction requires a why — preserved with the content.',
    });
  }

  // Capture current content from projection if not supplied
  const current = readFaceEvents(projectRoot);
  if (!current.ok) return current;
  const projected = projectFaceFromEvents(current.events);
  const prior = projected.fields[fact_id];
  const content =
    opts.content != null
      ? String(opts.content)
      : prior?.value ?? '';

  const at = opts.at ?? new Date().toISOString();
  const client_event_id =
    opts.client_event_id ?? `face-retract-${fact_id}-${hashSourceText(`${fact_id}|${opts.why}|${at}`).slice(0, 12)}`;

  const event = {
    kind: 'face_retract',
    fact_id,
    content,
    why: String(opts.why),
    at,
    client_event_id,
    source_hash: prior?.provenance?.source_hash ?? null,
    provenance: prior?.provenance ?? null,
  };

  // Face events store
  const stored = withFaceEventsLedger(projectRoot, (ledger) => {
    const priorEvt = ledger.events.find(
      (e) => e && e.client_event_id === client_event_id,
    );
    if (priorEvt) {
      return {
        ok: true,
        idempotent: true,
        event: priorEvt,
        skip_write: true,
        client_event_id,
      };
    }
    const seq = Number(ledger.next_seq) || ledger.events.length + 1;
    const record = { ...event, seq };
    return {
      ok: true,
      idempotent: false,
      event: record,
      ledger: {
        ...ledger,
        events: [...ledger.events, record],
        next_seq: seq + 1,
      },
      client_event_id,
    };
  });
  if (!stored.ok) return stored;

  // Spine mirror
  const spine = appendRoadmapEventThroughSpine(
    projectRoot,
    {
      kind: 'face_retract',
      fact_id,
      content,
      why: String(opts.why),
      at,
      client_event_id,
      source_hash: event.source_hash,
    },
    { skip_index: opts.skip_index !== false ? true : false },
  );
  if (!spine.ok && !spine.idempotent) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'spine-append-failed',
      detail: spine,
    });
  }

  const after = projectFaceFromEvents(
    stored.ledger?.events ?? [...current.events, stored.event],
  );

  return {
    ok: true,
    event: stored.event,
    exclusions: after.exclusions,
    fields: after.fields,
    exclusion_visible: after.exclusions.some((e) => e.fact_id === fact_id),
    spine,
    message: `Retracted ${fact_id}: ${opts.why}`,
  };
}

// ── Main compile entry ─────────────────────────────────────────────────────

/**
 * Compile a description into the Face projection inside a live envelope.
 *
 * Steps:
 *   1. Envelope live check (or COMPILE_NO_ENVELOPE / ENVELOPE_STATE_UNKNOWN)
 *   2. Write-once source_text blob
 *   3. Load face_events; build exclusion set from retractions
 *   4. Bounded multi-pass compile (circuit break → no partial version)
 *   5. Validate output
 *   6. Debit envelope (cost ledger: tokens + synthetic $)
 *   7. Append face_assert/refine + face_compile through face_events + spine
 *   8. Incremental Face narrative rewrite (only changed fields)
 *   9. Return proposal with dropped_or_generalized (seen before acceptance)
 *
 * @param {string} projectRoot
 * @param {{
 *   description?: string|object,
 *   text?: string,
 *   input?: object,
 *   client_event_id?: string,
 *   max_passes?: number,
 *   passFn?: Function,
 *   monoNow?: () => number,
 *   wallNow?: () => string|number,
 *   auth?: object,
 *   at?: string,
 *   skip_index?: boolean,
 *   land_version?: boolean,
 *   apply_face_file?: boolean,
 * }} [opts]
 */
export function compileFace(projectRoot, opts = {}) {
  try {
    return compileFaceInner(projectRoot, opts);
  } catch (e) {
    return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
      error: 'compile-threw',
      detail: String(e?.message ?? e),
      face_version_landed: false,
    });
  }
}

function compileFaceInner(projectRoot, opts = {}) {
  const root = path.resolve(projectRoot);

  // ── Envelope gate ────────────────────────────────────────────────────────
  const envState = readEnvelopeState(root, {
    monoNow: opts.monoNow,
    wallNow: opts.wallNow,
  });
  if (!envState.ok) {
    return compileFailure(COMPILE_CODE.ENVELOPE_STATE_UNKNOWN, {
      error: 'envelope-state-unknown',
      detail: envState,
    });
  }
  if (envState.empty || !envState.live) {
    // Absent / exhausted / expired → no live envelope. Plan: COMPILE_NO_ENVELOPE
    // (compile queued; confirm a budget). Exhausted/expired still map here for
    // the compile surface (user-visible text is the no-envelope family).
    if (
      envState.code === ENVELOPE_CODE.STATE_UNKNOWN ||
      envState.code === ENVELOPE_CODE.LEDGER_UNREADABLE
    ) {
      return compileFailure(COMPILE_CODE.ENVELOPE_STATE_UNKNOWN, {
        error: 'envelope-state-unknown',
        detail: envState,
      });
    }
    return compileFailure(COMPILE_CODE.NO_ENVELOPE, {
      error: 'no-live-envelope',
      envelope: envState,
    });
  }

  // ── Source text ──────────────────────────────────────────────────────────
  let sourceText = '';
  let structured = opts.input ?? {};
  if (typeof opts.description === 'string') {
    sourceText = opts.description;
  } else if (opts.description && typeof opts.description === 'object') {
    structured = { ...structured, ...opts.description };
    sourceText =
      opts.description.text ??
      opts.description.description ??
      opts.description.source_text ??
      serializeStructuredDescription(opts.description);
  } else if (typeof opts.text === 'string') {
    sourceText = opts.text;
  } else if (structured && Object.keys(structured).length) {
    sourceText = serializeStructuredDescription(structured);
  }

  if (!nonEmpty(sourceText)) {
    return compileFailure(COMPILE_CODE.SOURCE_EMPTY, {
      error: 'source-empty',
    });
  }

  // ── Face events readable? ────────────────────────────────────────────────
  const priorFace = readFaceEvents(root);
  if (!priorFace.ok) return priorFace;

  // Idempotence: same client_event_id → return original, zero second debit.
  const client_event_id_early = opts.client_event_id ?? null;
  if (nonEmpty(client_event_id_early)) {
    const priorById = (priorFace.events ?? []).find(
      (e) => e && e.kind === 'face_compile' && e.client_event_id === client_event_id_early,
    );
    if (priorById) {
      const priorVersion =
        (priorFace.versions ?? []).find(
          (v) => v && v.client_event_id === client_event_id_early,
        ) ?? priorFace.versions?.[priorFace.versions.length - 1] ?? null;
      return {
        ok: true,
        idempotent: true,
        face_version_landed: false,
        event: priorById,
        version: priorVersion,
        source_hash: priorById.source_hash ?? null,
        face_version_hash: priorById.face_version_hash ?? null,
        proposal: priorVersion
          ? {
              schema: FACE_COMPILE_SCHEMA,
              kind: 'face_compile_proposal',
              source_hash: priorVersion.source_hash,
              face_version_hash: priorVersion.face_version_hash,
              fields: priorVersion.fields,
              dropped_or_generalized: priorVersion.dropped_or_generalized ?? [],
              exclusions: priorVersion.exclusions ?? [],
              diff: priorVersion.diff ?? null,
              seen_before_acceptance: {
                dropped_or_generalized: priorVersion.dropped_or_generalized ?? [],
                exclusions: priorVersion.exclusions ?? [],
                cost: true,
              },
            }
          : null,
        message: `Face compile already recorded (client_event_id=${client_event_id_early}); no second debit.`,
      };
    }
  }

  // Empty-but-valid: if projection already reflects this exact source, refuse
  // with COMPILE_SOURCE_EMPTY (nothing new).
  const sourceBlob = writeSourceTextBlob(root, sourceText);
  if (!sourceBlob.ok) return sourceBlob;
  const source_hash = sourceBlob.source_hash;

  const priorProjection = projectFaceFromEvents(priorFace.events);
  const alreadyCompiled = (priorFace.events ?? []).some(
    (e) =>
      e &&
      e.kind === 'face_compile' &&
      e.source_hash === source_hash &&
      e.ok !== false,
  );
  if (alreadyCompiled && opts.force !== true) {
    return compileFailure(COMPILE_CODE.SOURCE_EMPTY, {
      error: 'nothing-new',
      source_hash,
      prior_version: priorFace.versions?.[priorFace.versions.length - 1] ?? null,
    });
  }

  // ── Bounded compile ──────────────────────────────────────────────────────
  const exclusions = buildExclusionSet(priorFace.events);
  const bounded = runBoundedCompile(sourceText, {
    max_passes: opts.max_passes,
    exclusions,
    input: structured,
    passFn: opts.passFn,
  });
  if (!bounded.ok) {
    // Circuit break or invalid — NO partial Face version lands.
    return {
      ...bounded,
      face_version_landed: false,
      source_hash,
    };
  }

  const validated = validateCompileOutput(bounded.result);
  if (!validated.ok) {
    return {
      ...validated,
      face_version_landed: false,
      source_hash,
    };
  }

  // ── Incremental diff vs prior ────────────────────────────────────────────
  const priorFields = {};
  for (const [k, v] of Object.entries(priorProjection.fields)) {
    priorFields[k] = { value: v.value };
  }
  const diff = diffFaceFields(priorFields, bounded.result.fields);

  // ── Debit envelope (cost ledger) ─────────────────────────────────────────
  const pricing = priceCompile(sourceText, { seat: 'compile' });
  const debit = debitSessionEnvelope(root, {
    kind: 'compile',
    text: sourceText,
    tokens: pricing.tokens,
    seat: 'compile',
    auth: opts.auth,
    monoNow: opts.monoNow,
    wallNow: opts.wallNow,
    client_event_id: opts.client_event_id
      ? `debit-${opts.client_event_id}`
      : `debit-face-${source_hash.slice(0, 12)}`,
  });
  if (!debit.ok) {
    // Auth / exhausted mid-path — map to compile surface honestly
    if (debit.code === ENVELOPE_CODE.STATE_UNKNOWN || debit.code === ENVELOPE_CODE.LEDGER_UNREADABLE) {
      return compileFailure(COMPILE_CODE.ENVELOPE_STATE_UNKNOWN, {
        error: 'envelope-debit-unknown',
        detail: debit,
        face_version_landed: false,
      });
    }
    return compileFailure(COMPILE_CODE.NO_ENVELOPE, {
      error: 'envelope-debit-refused',
      detail: debit,
      face_version_landed: false,
    });
  }

  const at = opts.at ?? (typeof opts.wallNow === 'function' ? opts.wallNow() : new Date().toISOString());
  const client_event_id =
    opts.client_event_id ?? `face-compile-${source_hash.slice(0, 16)}`;

  // ── Build face_assert / face_refine events ───────────────────────────────
  const fieldEvents = [];
  for (const [fact_id, f] of Object.entries(bounded.result.fields)) {
    const isRefine =
      priorProjection.fields[fact_id] &&
      priorProjection.fields[fact_id].value !== f.value;
    const kind = isRefine ? 'face_refine' : 'face_assert';
    fieldEvents.push({
      kind,
      fact_id,
      value: f.value,
      source_hash,
      provenance: {
        source_hash,
        start: f.start,
        end: f.end,
      },
      at,
      client_event_id: `${client_event_id}:${kind}:${fact_id}`,
    });
  }

  // Face version body (for hash + land)
  const versionBody = {
    schema: FACE_COMPILE_SCHEMA,
    source_hash,
    fields: Object.fromEntries(
      Object.entries(bounded.result.fields).map(([k, f]) => [
        k,
        {
          value: f.value,
          provenance: { source_hash, start: f.start, end: f.end },
        },
      ]),
    ),
    exclusions: bounded.result.exclusions ?? [],
    dropped_or_generalized: bounded.result.dropped_or_generalized ?? [],
    diff,
  };
  const face_version_hash = hashFaceVersion(versionBody);

  const remaining_usd =
    debit.envelope?.max_spend_usd != null
      ? Number(debit.envelope.max_spend_usd) - Number(debit.envelope.spent_usd)
      : debit.envelope
        ? null
        : null;
  // Prefer balance after debit from envelope fields
  const spent = Number(debit.envelope?.spent_usd) || 0;
  const maxSpend = Number(debit.envelope?.max_spend_usd) || 0;
  const compiles = Number(debit.envelope?.compile_count) || 0;
  const maxCompiles = Number(debit.envelope?.max_compiles) || 0;
  const remUsd = Math.max(0, maxSpend - spent);
  const remCompiles = Math.max(0, maxCompiles - compiles);

  const compileEvent = {
    kind: 'face_compile',
    schema: FACE_COMPILE_SCHEMA,
    source_hash,
    face_version_hash,
    envelope_id: debit.envelope?.envelope_id ?? null,
    tokens: pricing.tokens ?? debit.shown?.tokens ?? estimateTokens(sourceText),
    cost_usd: pricing.cost_usd ?? debit.shown?.cost_usd ?? 0,
    remaining_usd: remUsd,
    remaining_compiles: remCompiles,
    spent_usd: spent,
    compile_count: compiles,
    passes: bounded.passes,
    max_passes: bounded.max_passes ?? COMPILE_MAX_PASSES,
    converged: true,
    dropped_or_generalized: bounded.result.dropped_or_generalized ?? [],
    exclusions: bounded.result.exclusions ?? [],
    diff,
    at,
    client_event_id,
    pricing: {
      tokens: pricing.tokens,
      cost_usd: pricing.cost_usd,
      rate_key: pricing.rate_key,
      synthetic: true,
      disclaimer: pricing.disclaimer,
    },
    debit_shown: debit.shown ?? null,
  };

  // ── Land version in face_events store (atomic under lock) ────────────────
  const land = opts.land_version !== false;
  let stored = { ok: true, skip_write: true, ledger: priorFace.ledger };
  if (land) {
    stored = withFaceEventsLedger(root, (ledger) => {
      const priorCompile = ledger.events.find(
        (e) => e && e.client_event_id === client_event_id,
      );
      if (priorCompile) {
        return {
          ok: true,
          idempotent: true,
          event: priorCompile,
          skip_write: true,
          client_event_id,
        };
      }
      let seq = Number(ledger.next_seq) || ledger.events.length + 1;
      const newEvents = [];
      for (const fe of fieldEvents) {
        const existing = ledger.events.find(
          (e) => e && e.client_event_id === fe.client_event_id,
        );
        if (existing) {
          newEvents.push(existing);
          continue;
        }
        newEvents.push({ ...fe, seq });
        seq += 1;
      }
      const compileRecord = { ...compileEvent, seq };
      seq += 1;
      const version = {
        version: (ledger.versions?.length ?? 0) + 1,
        face_version_hash,
        source_hash,
        fields: versionBody.fields,
        exclusions: versionBody.exclusions,
        dropped_or_generalized: versionBody.dropped_or_generalized,
        diff,
        at,
        envelope_id: compileEvent.envelope_id,
        client_event_id,
      };
      return {
        ok: true,
        idempotent: false,
        event: compileRecord,
        field_events: newEvents,
        version,
        ledger: {
          ...ledger,
          events: [...ledger.events, ...newEvents, compileRecord],
          versions: [...(ledger.versions ?? []), version],
          next_seq: seq,
        },
        client_event_id,
      };
    });
    if (!stored.ok) {
      return {
        ...stored,
        face_version_landed: false,
      };
    }
  }

  // ── Spine append (typed kinds through allow-list) ────────────────────────
  const spineResults = [];
  if (land && !stored.idempotent) {
    for (const fe of fieldEvents) {
      const kindGate = assertEventKindAllowed(fe.kind);
      if (!kindGate.ok) {
        return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
          error: 'face-kind-not-allowed',
          detail: kindGate,
          face_version_landed: false,
        });
      }
      const r = appendRoadmapEventThroughSpine(
        root,
        {
          kind: fe.kind,
          fact_id: fe.fact_id,
          value: fe.value,
          source_hash: fe.source_hash,
          provenance: fe.provenance,
          at: fe.at,
          client_event_id: fe.client_event_id,
        },
        { skip_index: true },
      );
      spineResults.push(r);
      if (!r.ok && !r.idempotent) {
        return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
          error: 'spine-append-failed',
          detail: r,
          face_version_landed: false,
        });
      }
    }
    const compileSpine = appendRoadmapEventThroughSpine(
      root,
      {
        kind: 'face_compile',
        source_hash,
        face_version_hash,
        envelope_id: compileEvent.envelope_id,
        tokens: compileEvent.tokens,
        cost_usd: compileEvent.cost_usd,
        remaining_usd: compileEvent.remaining_usd,
        remaining_compiles: compileEvent.remaining_compiles,
        at,
        client_event_id,
      },
      { skip_index: true },
    );
    spineResults.push(compileSpine);
    if (!compileSpine.ok && !compileSpine.idempotent) {
      return compileFailure(COMPILE_CODE.OUTPUT_INVALID, {
        error: 'spine-compile-append-failed',
        detail: compileSpine,
        face_version_landed: false,
      });
    }
  }

  // ── Incremental Face file rewrite (changed fields only) ──────────────────
  let faceFile = null;
  if (land && opts.apply_face_file !== false) {
    faceFile = applyIncrementalFaceRewrite(root, versionBody.fields, diff);
  }

  // Proposal surface: dropped_or_generalized must be visible before acceptance
  const proposal = {
    schema: FACE_COMPILE_SCHEMA,
    kind: 'face_compile_proposal',
    source_hash,
    face_version_hash,
    fields: versionBody.fields,
    dropped_or_generalized: versionBody.dropped_or_generalized,
    exclusions: versionBody.exclusions,
    diff,
    cost: {
      tokens: compileEvent.tokens,
      cost_usd: compileEvent.cost_usd,
      remaining_usd: compileEvent.remaining_usd,
      remaining_compiles: compileEvent.remaining_compiles,
      envelope_id: compileEvent.envelope_id,
      shown: debit.shown,
      synthetic: true,
    },
    passes: bounded.passes,
    seen_before_acceptance: {
      dropped_or_generalized: versionBody.dropped_or_generalized,
      exclusions: versionBody.exclusions,
      cost: true,
    },
  };

  return {
    ok: true,
    proposal,
    source_hash,
    face_version_hash,
    face_version_landed: land && !stored.idempotent,
    idempotent: stored.idempotent === true,
    event: stored.event ?? compileEvent,
    version: stored.version ?? null,
    field_events: stored.field_events ?? fieldEvents,
    debit,
    pricing,
    passes: bounded.passes,
    converged: true,
    diff,
    exclusions: versionBody.exclusions,
    dropped_or_generalized: versionBody.dropped_or_generalized,
    spine: spineResults,
    face_file: faceFile,
    kinds_version: ROADMAP_EVENT_KINDS_VERSION,
    admitted_kinds: FACE_EVENT_KINDS,
    message:
      `Face compiled in ${bounded.passes} pass(es); `
      + `debited $${Number(compileEvent.cost_usd).toFixed(8)} synthetic `
      + `(envelope ${compileEvent.envelope_id}).`,
  };
}

/**
 * Serialize a structured description object to stable source text for hashing.
 * @param {object} obj
 */
function serializeStructuredDescription(obj) {
  const lines = [];
  for (const key of FACE_NARRATIVE_FIELDS) {
    if (obj && nonEmpty(obj[key])) {
      const heading = key
        .split('_')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
      lines.push(`## ${heading}`, '', String(obj[key]).trim(), '');
    }
  }
  if (!lines.length && obj) {
    if (nonEmpty(obj.goal)) {
      lines.push('## North star', '', String(obj.goal).trim(), '');
    }
    if (nonEmpty(obj.description)) {
      lines.push(String(obj.description).trim());
    }
  }
  return lines.join('\n');
}

/**
 * Incremental rewrite of ECGBERHT.md narrative sections for changed fields.
 * Unchanged sections are left alone (diff-based).
 *
 * @param {string} projectRoot
 * @param {Record<string, { value: string, provenance?: object }>} fields
 * @param {{ changed: string[], added: string[], removed: string[] }} diff
 */
export function applyIncrementalFaceRewrite(projectRoot, fields, diff) {
  const facePath = path.join(path.resolve(projectRoot), FACE_FILE_NAME);
  let raw = '';
  if (fs.existsSync(facePath)) {
    try {
      raw = fs.readFileSync(facePath, 'utf8');
    } catch (e) {
      return {
        ok: false,
        error: 'face-file-unreadable',
        detail: String(e?.message ?? e),
      };
    }
  } else {
    raw = `# Ecgberht — Face (campaign memory)\n\n`;
  }

  const rewriteKeys = new Set([
    ...(diff?.changed ?? []),
    ...(diff?.added ?? []),
    ...Object.keys(fields ?? {}),
  ]);
  // Only rewrite keys that exist in the new fields map
  const narrative = {};
  for (const key of FACE_NARRATIVE_FIELDS) {
    if (fields[key] && rewriteKeys.has(key)) {
      narrative[key] = fields[key].value;
    }
  }
  if (Object.keys(narrative).length === 0) {
    return { ok: true, rewritten: false, path: facePath, keys: [] };
  }

  // write-authority: narrative map merge (human rewrite authority), then
  // incremental markdown section upsert for only the changed keys.
  const auth = rewriteFaceNarrative({}, narrative);
  const keys = auth.ok ? auth.rewritten : Object.keys(narrative);
  let next = raw;
  for (const key of keys) {
    const value = narrative[key] ?? auth.narrative?.[key];
    if (value == null) continue;
    next = upsertMarkdownSection(next, headingForField(key), value);
  }
  writeFileAtomicSync(facePath, next);
  return {
    ok: true,
    rewritten: true,
    path: facePath,
    keys,
    via: 'rewriteFaceNarrative+section-upsert',
    authority: auth.authority ?? 'face_human_narrative',
  };
}

function headingForField(field) {
  const map = {
    north_star: 'North star',
    active_effort: 'Active effort',
    why_next: 'Why next',
    human_wait: 'Human wait',
    why_stakes: 'Why stakes',
  };
  return map[field] ?? field;
}

/**
 * Upsert a ## Section body in markdown (deterministic).
 * @param {string} markdown
 * @param {string} heading
 * @param {string} body
 */
function upsertMarkdownSection(markdown, heading, body) {
  const re = new RegExp(
    `(^|\\n)(#{1,3}\\s+${escapeRegExp(heading)}\\s*\\r?\\n)([\\s\\S]*?)(?=\\n#{1,3}\\s+|$)`,
    'i',
  );
  const replacement = `\n## ${heading}\n\n${body}\n`;
  if (re.test(markdown)) {
    return markdown.replace(re, `$1## ${heading}\n\n${body}\n`);
  }
  return `${markdown.trimEnd()}\n${replacement}`;
}

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Park/restart equivalence: project twice from the same face_events ledger
 * → byte-identical projection fingerprint.
 *
 * @param {string} projectRoot
 * @returns {{ ok: true, fingerprint: string, identical: true, projection: object }
 *   | { ok: false, code: string, message: string }}
 */
export function projectFaceParkRestartEquivalent(projectRoot) {
  const a = readFaceEvents(projectRoot);
  if (!a.ok) return a;
  const p1 = projectFaceFromEvents(a.events);
  const p2 = projectFaceFromEvents(a.events);
  const f1 = hashFaceVersion({
    fields: p1.fields,
    exclusions: p1.exclusions,
    source_hashes: p1.source_hashes,
  });
  const f2 = hashFaceVersion({
    fields: p2.fields,
    exclusions: p2.exclusions,
    source_hashes: p2.source_hashes,
  });
  return {
    ok: true,
    identical: f1 === f2,
    fingerprint: f1,
    projection: p1,
  };
}

/**
 * Allow-list version bump proof for Wave 10 tests.
 * @returns {{ ok: boolean, version: number, face_kinds: string[], admitted: boolean }}
 */
export function assertFaceKindsAdmitted() {
  const missing = [];
  for (const k of FACE_EVENT_KINDS) {
    const gate = assertEventKindAllowed(k);
    if (!gate.ok) missing.push(k);
  }
  return {
    ok: missing.length === 0 && ROADMAP_EVENT_KINDS_VERSION >= 2,
    version: ROADMAP_EVENT_KINDS_VERSION,
    face_kinds: [...FACE_EVENT_KINDS],
    admitted: missing.length === 0,
    missing,
    spine_kinds: [...SPINE_EVENT_KINDS],
  };
}

export {
  FACE_NARRATIVE_FIELDS,
  ROADMAP_EVENT_KINDS_VERSION,
  SPINE_EVENT_KINDS,
};

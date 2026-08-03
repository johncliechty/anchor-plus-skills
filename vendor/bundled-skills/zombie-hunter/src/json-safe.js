// W7 / SC4 — JSON-safe process field enum (control-char safe).
//
// Process cmdline / image paths can contain C0/C1 control characters that break
// JSON parsers or inject silent parse failures. Sweep worker + server use this
// module so parse fail ⇒ sweepError + abstain, never invented RED zombies.

/** C0 controls excluding TAB/LF/CR (those are common and JSON-safe when escaped). */
const C0_STRIP_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g;
/** C1 controls + DEL. */
const C1_STRIP_RE = /[\u007F-\u009F]/g;
/** Unpaired surrogates that break some JSON consumers. */
const SURROGATE_RE = /[\uD800-\uDFFF]/g;
// Non-global twins for hasUnsafeControlChars — /g + RegExp#test is stateful
// (lastIndex sticks across calls and can miss later inputs after a hit).
const C0_DETECT_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/;
const C1_DETECT_RE = /[\u007F-\u009F]/;
const SURROGATE_DETECT_RE = /[\uD800-\uDFFF]/;

/**
 * True if string contains control characters that are unsafe for process JSON
 * transport even after JSON.stringify (we still sanitize them).
 *
 * Detection regexes are intentionally non-global: RegExp#test with /g retains
 * lastIndex across calls, so a hit on one string can miss controls on the next.
 * @param {unknown} s
 * @returns {boolean}
 */
function hasUnsafeControlChars(s) {
  if (s == null) return false;
  const str = String(s);
  return C0_DETECT_RE.test(str) || C1_DETECT_RE.test(str) || SURROGATE_DETECT_RE.test(str);
}

/**
 * Replace control chars with a visible safe placeholder so JSON stays parseable
 * and operators can still see that the field was sanitized.
 * @param {unknown} s
 * @returns {string}
 */
function sanitizeControlChars(s) {
  if (s == null) return '';
  return String(s)
    .replace(C0_STRIP_RE, '\uFFFD')
    .replace(C1_STRIP_RE, '\uFFFD')
    .replace(SURROGATE_RE, '\uFFFD');
}

/**
 * Sanitize process fields commonly present on classify/engine rows.
 * @param {object} proc
 * @returns {object}
 */
function sanitizeProcessFields(proc) {
  if (!proc || typeof proc !== 'object') return proc;
  const out = { ...proc };
  for (const key of ['cmd', 'commandLine', 'CommandLine', 'sample']) {
    if (out[key] != null) out[key] = sanitizeControlChars(out[key]);
  }
  for (const key of ['path', 'imagePath', 'ExecutablePath', 'image', 'name', 'Name']) {
    if (out[key] != null) out[key] = sanitizeControlChars(out[key]);
  }
  if (Array.isArray(out.engines)) {
    out.engines = out.engines.map((e) => sanitizeProcessFields(e));
  }
  if (Array.isArray(out.hiddenSample)) {
    out.hiddenSample = out.hiddenSample.map((x) => sanitizeControlChars(x));
  }
  return out;
}

/**
 * Deep-sanitize string leaves on an object tree (bounded depth).
 * @param {unknown} value
 * @param {number} [depth]
 * @returns {unknown}
 */
function sanitizeTree(value, depth = 0) {
  if (depth > 12) return value;
  if (typeof value === 'string') return sanitizeControlChars(value);
  if (Array.isArray(value)) return value.map((v) => sanitizeTree(v, depth + 1));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = sanitizeTree(v, depth + 1);
    }
    return out;
  }
  return value;
}

/**
 * JSON.stringify after control-char sanitization of process-shaped payloads.
 * Always produces parseable JSON (or throws only on non-JSON types like BigInt).
 * @param {unknown} value
 * @returns {string}
 */
function jsonSafeStringify(value) {
  const clean = sanitizeTree(value);
  return JSON.stringify(clean);
}

/**
 * Parse sweep worker stdout. On any failure returns abstain-shaped result:
 * ok:false, sweepError set, empty engines — never invents zombies.
 *
 * @param {string} raw
 * @returns {{
 *   ok: boolean,
 *   sweepError: string|null,
 *   engines: Array,
 *   hiddenNonEngine: number,
 *   hiddenSample: Array,
 *   ledger: object,
 *   parseFailed: boolean,
 *   controlCharSanitized: boolean,
 *   [key: string]: unknown
 * }}
 */
function parseSweepJson(raw) {
  const empty = {
    ok: false,
    sweepError: null,
    engines: [],
    hiddenNonEngine: 0,
    hiddenSample: [],
    ledger: {
      sessions: [],
      totals: { activeSessions: 0, usdRecent: 0, usdPerMin: 0, tokensRecent: 0 },
      windowMin: 10,
    },
    parseFailed: true,
    controlCharSanitized: false,
  };

  if (raw == null || String(raw).trim() === '') {
    return { ...empty, sweepError: 'empty sweep output' };
  }

  let text = String(raw);
  // Strip BOM / leading noise that sometimes appears before JSON.
  text = text.replace(/^\uFEFF/, '').trim();
  // If stdout mixed logs, try first {...} blob.
  if (text[0] !== '{' && text[0] !== '[') {
    const start = text.indexOf('{');
    const end = text.lastIndexOf('}');
    if (start >= 0 && end > start) text = text.slice(start, end + 1);
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    // Retry after aggressive control-char strip (malformed raw).
    try {
      const cleaned = sanitizeControlChars(text);
      parsed = JSON.parse(cleaned);
    } catch (e2) {
      return {
        ...empty,
        sweepError: 'could not parse sweep result: ' + (e2 && e2.message ? e2.message : e.message),
        parseFailed: true,
      };
    }
  }

  if (!parsed || typeof parsed !== 'object') {
    return { ...empty, sweepError: 'sweep result is not an object' };
  }

  const sanitized = sanitizeProcessFields(parsed);
  const engines = Array.isArray(sanitized.engines) ? sanitized.engines : [];
  const ok = sanitized.ok !== false;
  const sweepError = ok
    ? null
    : (sanitized.error || sanitized.sweepError || 'sweep failed');

  // Parse failure or worker error ⇒ abstain shape (no invented RED).
  if (!ok || sweepError) {
    return {
      ...sanitized,
      ok: false,
      sweepError: sweepError || 'sweep failed',
      engines: [], // never invent zombies on error
      hiddenNonEngine: 0,
      hiddenSample: [],
      parseFailed: false,
      controlCharSanitized: true,
      abstain: true,
    };
  }

  return {
    ...sanitized,
    ok: true,
    sweepError: null,
    engines,
    hiddenNonEngine: sanitized.hiddenNonEngine || 0,
    hiddenSample: Array.isArray(sanitized.hiddenSample) ? sanitized.hiddenSample : [],
    ledger: sanitized.ledger || empty.ledger,
    parseFailed: false,
    controlCharSanitized: true,
    abstain: false,
  };
}

module.exports = {
  hasUnsafeControlChars,
  sanitizeControlChars,
  sanitizeProcessFields,
  sanitizeTree,
  jsonSafeStringify,
  parseSweepJson,
};

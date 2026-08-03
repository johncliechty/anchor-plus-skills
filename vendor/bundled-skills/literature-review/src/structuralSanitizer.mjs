// Wave 3 — structural sanitization for worker outputs.
// Everything a worker emits ultimately lands in a Markdown/HTML-rendered
// ledger, and the source material is untrusted — a paper's text can carry
// `<script>` tags, Markdown emphasis/links, or prototype-pollution keys.
// Sanitization here is AGGRESSIVE entity-encoding, not stripping: the
// characters remain readable in the output, but none of them can activate as
// HTML or Markdown structure.
//
//   - Every HTML-active character (& < > " ') is entity-encoded.
//   - Every INLINE Markdown-active character (` * _ [ ] ( ) # | ~ \ ! { } =)
//     is entity-encoded. Line-start-only markers (- + .) stay readable:
//     control characters — including every newline — are replaced with a
//     space, so sanitized text can never fabricate a line start of its own.
//   - C0/C1 control characters are replaced with a single space.
//   - Dangerous object keys (__proto__, constructor, prototype) are dropped.
//
// Sanitization is applied to OUTPUTS only, after grounding — strict
// exact-string quote matching always happens on unsanitized normalized text,
// and raw start/end offsets survive sanitization untouched, so the evidence
// lineage stays verifiable.

const ENTITY_MAP = new Map(Object.entries({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
  '`': '&#96;',
  '*': '&#42;',
  '_': '&#95;',
  '[': '&#91;',
  ']': '&#93;',
  '(': '&#40;',
  ')': '&#41;',
  '#': '&#35;',
  '|': '&#124;',
  '~': '&#126;',
  '\\': '&#92;',
  '!': '&#33;',
  '{': '&#123;',
  '}': '&#125;',
  '=': '&#61;'
}));

const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/** Entity-encode one string so it is inert in HTML and Markdown contexts. */
export function sanitizeText(value) {
  let out = '';
  for (const ch of String(value ?? '')) {
    const cp = ch.codePointAt(0);
    if (cp <= 0x1f || (cp >= 0x7f && cp <= 0x9f)) {
      out += ' ';
      continue;
    }
    out += ENTITY_MAP.get(ch) ?? ch;
  }
  return out;
}

/**
 * Deep-sanitize a JSON-shaped structure (the only shape worker IPC can carry):
 * every string — keys included — goes through sanitizeText; numbers, booleans
 * and null pass through untouched; dangerous keys are dropped. Throws on
 * cyclic input rather than recursing forever.
 */
export function sanitizeStructure(value, seen = new WeakSet()) {
  if (typeof value === 'string') return sanitizeText(value);
  if (Array.isArray(value)) {
    if (seen.has(value)) throw new TypeError('sanitizeStructure: cyclic structure');
    seen.add(value);
    return value.map((item) => sanitizeStructure(item, seen));
  }
  if (value !== null && typeof value === 'object') {
    if (seen.has(value)) throw new TypeError('sanitizeStructure: cyclic structure');
    seen.add(value);
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (UNSAFE_KEYS.has(key)) continue;
      out[sanitizeText(key)] = sanitizeStructure(item, seen);
    }
    return out;
  }
  return value;
}

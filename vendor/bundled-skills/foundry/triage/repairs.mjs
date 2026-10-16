// Small in-scope repairs (NS-01 criterion 8 / Wave 6).
//
// Doc-locator: DESCRIPTION.md + *-engine-design.md must resolve as the
// description/design role. Foreman's DOC_PATTERNS already match both via
// /description/i and /\bdesign\b/i — this module freezes the acceptance matrix
// and exports extended patterns for any consumer that still uses a narrower set.
//
// Prompt-size / shark JSON robustness: Crucible shark-tank + stage1 already
// switch to markdown-first when drafts are large (avoids JSON-parse ABSTAIN on
// LITE plans with fat context). This module records the status and exports the
// byte threshold contract so tests can pin "still not broken."

/** Wave-6 repairs stamp. */
export const NS01_WAVE6_REPAIRS_STAMP = 'ns01-w6-repairs';

/**
 * Filename patterns the Foreman doc-locator must accept for the description role.
 * Frozen acceptance matrix (heuristic basenames).
 */
export const DESCRIPTION_DOC_BASENAMES = Object.freeze([
  'DESCRIPTION.md',
  'description.md',
  'DESIGN.md',
  'design.md',
  'SPEC.md',
  'PRD.md',
  'north-star-engine-design.md',
  'legal-engine-design.md',
  'financial-engine-design.md',
  'foo-engine-design.md',
]);

/**
 * Extended description-role regexes (superset of trio foreman-lib DOC_PATTERNS).
 * Safe to merge into any locator that still lacks engine-design coverage.
 */
export const DESCRIPTION_DOC_PATTERNS = Object.freeze([
  /description/i,
  /\bdesign\b/i,
  /\bspec\b/i,
  /\bprd\b/i,
  /engine[-_ ]?design/i,
]);

/**
 * True when a basename would match the description role under NS-01 repairs.
 * @param {string} basename
 * @returns {boolean}
 */
export function isDescriptionDocBasename(basename) {
  if (typeof basename !== 'string' || !basename.trim()) return false;
  const name = basename.trim();
  return DESCRIPTION_DOC_PATTERNS.some((re) => re.test(name));
}

/**
 * Shark / revise markdown-first threshold (bytes of draft) — matches Crucible
 * stage1 REVISE_MARKDOWN_BYTES spirit and shark-tank draft.length > 20000 path.
 * Below this, schema JSON is fine; at/above, markdown-first avoids ABSTAIN.
 */
export const PROMPT_SIZE_MARKDOWN_FIRST_BYTES = 20_000;

/**
 * Whether a draft should use markdown-first (prompt-size robustness).
 * @param {string | Buffer | number} draftOrByteLength
 * @returns {boolean}
 */
export function shouldUseMarkdownFirst(draftOrByteLength) {
  let n;
  if (typeof draftOrByteLength === 'number') n = draftOrByteLength;
  else if (typeof draftOrByteLength === 'string') {
    n = Buffer.byteLength(draftOrByteLength, 'utf8');
  } else if (Buffer.isBuffer(draftOrByteLength)) n = draftOrByteLength.length;
  else n = 0;
  return n >= PROMPT_SIZE_MARKDOWN_FIRST_BYTES;
}

/**
 * Status of criterion-8 small repairs as of Wave 6.
 * @returns {Readonly<object>}
 */
export function repairsStatus() {
  return Object.freeze({
    stamp: NS01_WAVE6_REPAIRS_STAMP,
    docLocator: Object.freeze({
      status: 'ok',
      note:
        'Foreman DOC_PATTERNS already accept DESCRIPTION.md and *design* basenames ' +
        '(including *-engine-design.md via /\\bdesign\\b/i). Extended patterns exported here.',
      acceptsDescription: true,
      acceptsEngineDesign: true,
    }),
    promptSize: Object.freeze({
      status: 'ok',
      note:
        'Crucible shark-tank + stage1 already use markdown-first for large drafts to avoid ' +
        'JSON-parse ABSTAIN; threshold pinned as PROMPT_SIZE_MARKDOWN_FIRST_BYTES.',
      markdownFirstBytes: PROMPT_SIZE_MARKDOWN_FIRST_BYTES,
    }),
    mirrorHashes: Object.freeze({
      status: 'ok',
      note:
        'researchPrime governance.mjs byte-identity is Wave-5 baseline; Wave 6 does not alter it.',
    }),
  });
}

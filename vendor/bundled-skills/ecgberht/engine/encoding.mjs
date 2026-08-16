/**
 * W1 - encoding integrity: the UTF-8-read-as-CP1252 mojibake detector.
 *
 * WHY. Several documents under planning/ carry the same injury: text that was written as
 * UTF-8, read back byte-for-byte as Windows-1252, and re-encoded as UTF-8. An em dash
 * (U+2014, bytes E2 80 94) comes out the far side as the three characters U+00E2 U+20AC
 * U+201D; run the accident a second time and it becomes an eight-character run starting
 * U+00C3 U+00A2. The result is still perfectly valid UTF-8, so no reader ever throws - it
 * is simply wrong, silently, forever.
 *
 * That matters far beyond cosmetics here. The portfolio index hashes file bytes and
 * rebuilds from them; ingesting a mojibake document would fold the damage into a content
 * hash, and every later "byte-equal rebuild" assertion would faithfully preserve garbage.
 * So the disease is named and caught at the pipeline, as a NAMED sub-state of garbage
 * rather than a generic parse failure: MOJIBAKE is distinct from INVALID_UTF8, and both
 * are distinct from CLEAN.
 *
 * This module's source is pure ASCII on purpose. The characters it hunts for are declared
 * as CODE POINTS and every byte signature is DERIVED at load time by replaying the
 * accident, so the detector's own source can never become a specimen of the disease it
 * detects - which is what lets the sweep "no engine/ source contains mojibake" include
 * this file instead of carving out an exception for it.
 *
 * Stdlib only. No runtime dependencies.
 */

import fs from 'node:fs';

// W3 landed STATUS-v1 as the single enum module, which inverts W1's note below: the
// detector now READS its verdict name from the enum instead of declaring it. Same
// guarantee - detector and enum cannot drift - but the literal exists in exactly one file,
// which is what test/w49-status-enum-lint.test.mjs enforces. status.mjs imports nothing,
// so there is no cycle.
import { INTEGRITY } from './portfolio/status.mjs';

/** Encoding verdicts. MOJIBAKE and INVALID_UTF8 are deliberately NOT the same state. */
export const ENCODING_STATUS = Object.freeze({
  CLEAN: 'CLEAN',
  MOJIBAKE: INTEGRITY.MOJIBAKE,
  INVALID_UTF8: 'INVALID_UTF8',
});

/** The named garbage sub-states, in the order the detector reports them. */
export const GARBAGE_SUBSTATES = Object.freeze([
  ENCODING_STATUS.MOJIBAKE,
  ENCODING_STATUS.INVALID_UTF8,
]);

/** The sub-state this module exists to name. */
export const MOJIBAKE = ENCODING_STATUS.MOJIBAKE;

/**
 * Windows-1252 bytes 0x80-0x9F that differ from Latin-1. Everything else in 0x00-0xFF is
 * the identity mapping. 0x81, 0x8D, 0x8F, 0x90 and 0x9D are UNDEFINED in CP1252; lenient
 * decoders pass them through unchanged, and the damaged documents in planning/ prove that
 * is exactly what happened, so pass-through is what is modelled here.
 */
const CP1252_HIGH = new Map([
  [0x80, 0x20ac], [0x82, 0x201a], [0x83, 0x0192], [0x84, 0x201e],
  [0x85, 0x2026], [0x86, 0x2020], [0x87, 0x2021], [0x88, 0x02c6],
  [0x89, 0x2030], [0x8a, 0x0160], [0x8b, 0x2039], [0x8c, 0x0152],
  [0x8e, 0x017d], [0x91, 0x2018], [0x92, 0x2019], [0x93, 0x201c],
  [0x94, 0x201d], [0x95, 0x2022], [0x96, 0x2013], [0x97, 0x2014],
  [0x98, 0x02dc], [0x99, 0x2122], [0x9a, 0x0161], [0x9b, 0x203a],
  [0x9c, 0x0153], [0x9e, 0x017e], [0x9f, 0x0178],
]);

/**
 * Decode bytes as Windows-1252 - i.e. commit the first half of the accident on purpose.
 *
 * @param {Buffer|Uint8Array|number[]} bytes
 * @returns {string}
 */
export function decodeCp1252(bytes) {
  let out = '';
  for (const b of bytes) {
    out += String.fromCharCode(b < 0x80 ? b : (CP1252_HIGH.get(b) ?? b));
  }
  return out;
}

/**
 * Replay the accident once: encode as UTF-8, read the bytes back as CP1252.
 *
 * @param {string} text
 * @returns {string} the damaged form
 */
export function mojibakeOnce(text) {
  return decodeCp1252(Buffer.from(String(text), 'utf8'));
}

/**
 * The characters this repo's prose actually uses that survive the accident with a
 * distinctive multi-byte signature. Declared as code points so this file stays ASCII.
 */
const SOURCE_CHARS = Object.freeze(
  [
    [0x2014, 'EM_DASH'],
    [0x2013, 'EN_DASH'],
    [0x2018, 'LEFT_SINGLE_QUOTE'],
    [0x2019, 'RIGHT_SINGLE_QUOTE'],
    [0x201c, 'LEFT_DOUBLE_QUOTE'],
    [0x201d, 'RIGHT_DOUBLE_QUOTE'],
    [0x2026, 'ELLIPSIS'],
    [0x2022, 'BULLET'],
    [0x2190, 'LEFT_ARROW'],
    [0x2192, 'RIGHT_ARROW'],
    [0x2713, 'CHECK_MARK'],
    [0x00a0, 'NBSP'],
    [0x00b7, 'MIDDLE_DOT'],
    [0x00d7, 'MULTIPLICATION_SIGN'],
    [0x00e9, 'E_ACUTE'],
    [0x00fc, 'U_DIAERESIS'],
  ].map(([codePoint, name]) => [String.fromCodePoint(codePoint), name]),
);

/** How many applications of the accident are modelled. */
export const MAX_MOJIBAKE_DEPTH = 2;

/** @returns {Array<{name:string, depth:number, original:string, damaged:string, bytes:Buffer}>} */
function buildSignatures() {
  const sigs = [];
  for (const [original, name] of SOURCE_CHARS) {
    let damaged = original;
    for (let depth = 1; depth <= MAX_MOJIBAKE_DEPTH; depth += 1) {
      damaged = mojibakeOnce(damaged);
      sigs.push({
        name: `${name}_L${depth}`,
        depth,
        original,
        damaged,
        bytes: Buffer.from(damaged, 'utf8'),
      });
    }
  }
  // Longest first, and that ordering is load-bearing twice over: a depth-2 signature must
  // be matched (and repaired) before the depth-1 fragments nested inside it, or the same
  // injury gets counted twice and repaired only halfway.
  sigs.sort((a, b) => b.bytes.length - a.bytes.length || a.name.localeCompare(b.name));
  return sigs;
}

/**
 * Byte signatures, longest first.
 *
 * @type {ReadonlyArray<{name:string, depth:number, original:string, damaged:string, bytes:Buffer}>}
 */
export const MOJIBAKE_SIGNATURES = Object.freeze(buildSignatures());

/**
 * @param {Buffer|Uint8Array} bytes
 * @returns {boolean} whether the bytes decode as strict UTF-8
 */
export function isValidUtf8(bytes) {
  try {
    new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(bytes));
    return true;
  } catch {
    return false;
  }
}

/**
 * Scan raw bytes for the mojibake signature set.
 *
 * The offending BYTE OFFSET is the point of this function. A caller that only learned
 * "this file is damaged" would have to re-find the damage by hand, and a caller that
 * learned a CHARACTER offset would be pointing at a position that does not exist in the
 * byte stream it is about to hash.
 *
 * @param {Buffer|Uint8Array|string} input
 * @returns {{
 *   status: string, substate: string|null, clean: boolean, valid_utf8: boolean,
 *   byte_length: number, first_offset: number|null,
 *   findings: Array<{offset:number, byte_length:number, signature:string, depth:number, damaged:string, original:string}>
 * }}
 */
export function scanBytesForMojibake(input) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(input);
  const claimed = new Uint8Array(buf.length);
  const findings = [];

  for (const sig of MOJIBAKE_SIGNATURES) {
    let from = 0;
    for (;;) {
      const at = buf.indexOf(sig.bytes, from);
      if (at < 0) break;
      from = at + 1;

      let overlaps = false;
      for (let i = at; i < at + sig.bytes.length; i += 1) {
        if (claimed[i]) { overlaps = true; break; }
      }
      // A depth-1 fragment sitting inside an already-claimed depth-2 run is the SAME
      // injury, not a second one.
      if (overlaps) continue;

      for (let i = at; i < at + sig.bytes.length; i += 1) claimed[i] = 1;
      findings.push({
        offset: at,
        byte_length: sig.bytes.length,
        signature: sig.name,
        depth: sig.depth,
        damaged: sig.damaged,
        original: sig.original,
      });
    }
  }

  findings.sort((a, b) => a.offset - b.offset);
  const valid = isValidUtf8(buf);
  const status = findings.length
    ? ENCODING_STATUS.MOJIBAKE
    : valid
      ? ENCODING_STATUS.CLEAN
      : ENCODING_STATUS.INVALID_UTF8;

  return {
    status,
    substate: status === ENCODING_STATUS.CLEAN ? null : status,
    clean: status === ENCODING_STATUS.CLEAN,
    valid_utf8: valid,
    byte_length: buf.length,
    first_offset: findings.length ? findings[0].offset : null,
    findings,
  };
}

/**
 * Scan a file on disk.
 *
 * @param {string} filePath
 * @returns {ReturnType<typeof scanBytesForMojibake> & {path: string}}
 */
export function scanFileForMojibake(filePath) {
  // encoding-lint: raw-bytes - decoding to a string here would erase the very evidence
  // this function exists to find, so this read is deliberately left un-decoded.
  const bytes = fs.readFileSync(filePath);
  return { ...scanBytesForMojibake(bytes), path: filePath };
}

/**
 * Undo the accident on text, deepest damage first.
 *
 * Signature-directed rather than "run the whole string back through the CP1252 inverse":
 * a whole-string inverse mangles every character that was already correct, which would
 * turn a partially damaged document into a fully damaged one.
 *
 * @param {string} text
 * @returns {string}
 */
export function repairMojibakeText(text) {
  let out = String(text);
  for (const sig of MOJIBAKE_SIGNATURES) {
    if (out.includes(sig.damaged)) out = out.split(sig.damaged).join(sig.original);
  }
  return out;
}

/**
 * One human-readable line per finding, naming the file, the byte offset, the signature,
 * and what the character was before the damage.
 *
 * @param {{path?: string, findings?: Array<object>}} scan
 * @returns {string[]}
 */
export function describeMojibake(scan) {
  const where = scan.path ? `${scan.path}: ` : '';
  return (scan.findings ?? []).map(
    (f) => `${where}byte ${f.offset}: ${MOJIBAKE} ${f.signature} (was ${JSON.stringify(f.original)})`,
  );
}

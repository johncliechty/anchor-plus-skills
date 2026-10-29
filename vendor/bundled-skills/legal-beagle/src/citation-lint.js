// citation-lint.js — Rule 1 as STRUCTURE, not exhortation (W3, 2026-07-11;
// hardened 2026-10-23 per journal 0014 for standalone §/§§, multi-section lists,
// Section <title>-<ch>-<sec>, IRC §, formerly §, and native .docx extraction).
//
// Deterministically extracts citation-shaped strings from an output document and
// FAILS any citation that (a) appears in none of the provided source texts and
// (b) carries no [UNVERIFIED — ...] tag on its line. This is the last-line gate
// before findings are delivered: a fabricated citation has to get past a regex,
// not a promise.
//
//   node src/citation-lint.js <findings-file> <source-file...>
//   exit 0 = clean · exit 1 = ungrounded citation(s) (listed) · exit 2 = usage
//
// Citation shapes covered (deliberately broad — over-flagging is the safe error):
//   case reporters:  "597 U.S. 215", "142 S. Ct. 2111", "83 F.4th 1032"
//   case names:      "Smith v. Jones"
//   statutes/regs:   "26 U.S.C. § 2503", "Utah Code § 75B-1-101", "Treas. Reg. § 20.2031-1"
//   standalone §/§§: "§ 75B-1-303(1)(c)", "formerly § 75-2-1203", "§§ 75B-1-302, 75B-1-303, and 75B-1-304"
//   IRC / Section:   "IRC § 675(4)(C)", "Section 75B-1-306", "Section 7-5-1"
//   rulings:         "PLR 200944002", "Rev. Rul. 2023-2"

import fs from 'node:fs';
import zlib from 'node:zlib';

const CITATION_RES = [
  /\b\d{1,4}\s+(?:U\.?S\.?|S\.?\s?Ct\.?|F\.(?:2d|3d|4th)|F\.?\s?Supp\.?(?:\s?\d?d?)?|P\.(?:2d|3d)|A\.(?:2d|3d))\s+\d{1,5}\b/g,
  /\b[A-Z][A-Za-z'’.-]+\s+v\.?\s+[A-Z][A-Za-z'’.-]+\b/g,
  /\b\d{1,3}\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s*§+\s*[\w.()-]+/g,
  /\b(?:[A-Z][a-z]+\s)?Code\s*(?:Ann\.?\s*)?(?:§+|Sec\.?)\s*[\w.()-]+/g,
  /\bI\.?R\.?C\.?\s*§+\s*[\w.()-]+/g,
  /\bTreas\.?\s?Reg\.?\s*§+\s*[\w.()-]+/g,
  /\b(?:PLR|TAM)\s?\d{7,9}\b/g,
  /\bRev\.?\s?(?:Rul\.?|Proc\.?)\s?\d{2,4}-\d+\b/g,
  /\bSections?\s+\d+[A-Za-z0-9]*-[A-Za-z0-9.-]+(?:\([A-Za-z0-9]+\))*/g,
  /(?:\bformerly\s+)?§+\s*\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*/g,
];

// Multi-section list after §§ (e.g. "§§ 75B-1-302, 75B-1-303, and 75B-1-304(1)" or "IRC §§ 2036 & 2038")
const MULTI_SECTION_RE = /(?:(?:\b[A-Z][a-z]+\s+)?\bCode\s*(?:Ann\.?\s*)?|\bI\.?R\.?C\.?\s+|\b\d{1,3}\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s+)?§§\s*(\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*(?:\s*(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+|\s*[&/]\s*)\s*§*\s*\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*)+)/g;
const SECTION_TOKEN_RE = /\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*/g;

const norm = (s) => String(s)
  .replace(/[’]/g, "'")
  .replace(/§+\s*(\d)/g, '§ $1')
  .replace(/\s+/g, ' ')
  .trim()
  .toLowerCase();

function cleanCitationTail(raw) {
  let s = String(raw).trim().replace(/[.,;:]+$/, '');
  while (s.endsWith(')')) {
    const opens = (s.match(/\(/g) || []).length;
    const closes = (s.match(/\)/g) || []).length;
    if (closes > opens) s = s.slice(0, -1).replace(/[.,;:]+$/, '');
    else break;
  }
  return s;
}

/** Extract citation-shaped strings with their line numbers. */
export function extractCitations(text) {
  const out = [];
  const lines = String(text).split(/\r?\n/);
  lines.forEach((line, i) => {
    const spans = [];
    // 1. Expand multi-section lists (§§ A, B, and C) into individual § tokens so every item is gated.
    for (const m of line.matchAll(MULTI_SECTION_RE)) {
      const start = m.index ?? 0;
      const end = start + m[0].length;
      const tokens = [...m[1].matchAll(SECTION_TOKEN_RE)].map((t) => cleanCitationTail(t[0]));
      if (tokens.length >= 2) {
        spans.push({ start, end });
        for (const tok of tokens) {
          out.push({ citation: `§ ${tok}`, line: i + 1, lineText: line });
        }
      }
    }
    // 2. Standard and standalone citation patterns, skipping sub-spans already covered on this line.
    for (const re of CITATION_RES) {
      for (const m of line.matchAll(re)) {
        const start = m.index ?? 0;
        const end = start + m[0].length;
        if (spans.some((s) => start >= s.start && end <= s.end)) continue;
        spans.push({ start, end });
        out.push({ citation: cleanCitationTail(m[0]), line: i + 1, lineText: line });
      }
    }
  });
  return out;
}

/**
 * Determine whether a single extracted citation is grounded in at least one normalized source.
 * Exact normalized substring match always succeeds. For statutory section references
 * ("Section 75B-1-306", "Utah Code Ann. § 75B-1-306", "formerly § 75-2-1203", "§ 75B-1-303(2)(a)(ii)"),
 * also checks the canonical section/subsection token so "Section 75B-1-306" or "formerly § 75-2-1203"
 * matches a source containing "Utah Code § 75B-1-306" or raw legislature header "75B-1-306.",
 * while any fabricated section or subsection ("§ 75B-1-303(1)(c)", "§ 75B-2-1104") still fails closed.
 */
function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isCitationGrounded(citation, normalizedSources) {
  const n = norm(citation).replace(/[.,;:]+$/, '');
  const exactRe = new RegExp(`(?<![a-z0-9-])${escapeRegExp(n)}(?![a-z0-9-]|\\.\\d)`, 'i');
  if (normalizedSources.some((s) => exactRe.test(s))) return true;

  // Check if this is a statutory section citation with a section/subsection identifier
  const secMatch = citation.match(/(?:§+|Sections?|Sec\.?)\s*(\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*)/i);
  if (!secMatch) return false;
  const secToken = secMatch[1].replace(/[.,;:]+$/, '').toLowerCase();
  const escToken = escapeRegExp(secToken);
  const isHyphenatedCode = /^\d+[a-z0-9]*-\d+/i.test(secToken);
  const prefixedRe = new RegExp(`(?:§+|sec\\.|section)\\s*${escToken}(?![a-z0-9-]|\\.\\d)`, 'i');
  const bareCodeRe = new RegExp(`(?<![a-z0-9-])${escToken}(?![a-z0-9-]|\\.\\d)`, 'i');

  // Guard against wrong-title / wrong-state matches when an explicit title or state prefix is present
  const fedTitleMatch = citation.match(/^\s*(\d{1,3})\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\b/i);
  const stateCodeMatch = citation.match(/^\s*([A-Z][a-z]+)\s+Code\b/);
  const fedTitleRe = fedTitleMatch
    ? new RegExp(`\\b${escapeRegExp(fedTitleMatch[1])}\\s+(?:u\\.?s\\.?c\\.?|c\\.?f\\.?r\\.?)|\\btitle\\s+${escapeRegExp(fedTitleMatch[1])}\\b`, 'i')
    : null;
  const requiredState = stateCodeMatch ? stateCodeMatch[1].toLowerCase() : null;

  return normalizedSources.some((s) => {
    if (fedTitleRe && !fedTitleRe.test(s)) return false;
    if (requiredState && !s.includes(requiredState)) return false;
    if (prefixedRe.test(s)) return true;
    if (isHyphenatedCode && bareCodeRe.test(s)) return true;
    return false;
  });
}

/**
 * Lint: every extracted citation must be grounded in ≥1 source text OR its line
 * must carry an [UNVERIFIED...] tag. Returns { ok, violations[] }.
 */
export function lintCitations(findingsText, sourceTexts = []) {
  const sources = sourceTexts.map(norm);
  const violations = [];
  for (const c of extractCitations(findingsText)) {
    if (/\[unverified\b/i.test(c.lineText)) continue;              // honestly tagged
    const grounded = isCitationGrounded(c.citation, sources);
    if (!grounded) violations.push(c);
  }
  return { ok: violations.length === 0, violations };
}

// ── Native .docx extraction (Wave 2, 2026-10-23 — journal 0014) ──────────────
// Extracts active body paragraphs, <w:ins> tracked insertions, and word/comments.xml
// margin comments from a .docx zip archive while stripping <w:del> / <w:delText>
// tracked deletions so deleted legacy citations never trigger false violations.

function decodeXmlEntities(str) {
  return String(str)
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function readZipEntries(buf) {
  const entries = new Map();
  // Locate End of Central Directory (EOCD) signature 0x06054b50
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65558); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('Invalid .docx archive (EOCD not found)');
  const totalEntries = buf.readUInt16LE(eocd + 10);
  let cdPos = buf.readUInt32LE(eocd + 16);
  for (let idx = 0; idx < totalEntries && cdPos + 46 <= buf.length; idx++) {
    if (buf.readUInt32LE(cdPos) !== 0x02014b50) break;
    const method = buf.readUInt16LE(cdPos + 10);
    const compSize = buf.readUInt32LE(cdPos + 20);
    const nameLen = buf.readUInt16LE(cdPos + 28);
    const extraLen = buf.readUInt16LE(cdPos + 30);
    const commentLen = buf.readUInt16LE(cdPos + 32);
    const localOffset = buf.readUInt32LE(cdPos + 42);
    const name = buf.subarray(cdPos + 46, cdPos + 46 + nameLen).toString('utf8');
    cdPos += 46 + nameLen + extraLen + commentLen;
    if (localOffset + 30 > buf.length || buf.readUInt32LE(localOffset) !== 0x04034b50) continue;
    const lNameLen = buf.readUInt16LE(localOffset + 26);
    const lExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + lNameLen + lExtraLen;
    const compData = buf.subarray(dataStart, dataStart + compSize);
    if (method === 0) entries.set(name, compData);
    else if (method === 8) entries.set(name, zlib.inflateRawSync(compData));
  }
  return entries;
}

function xmlBlocksToParagraphs(xml, blockTag = 'w:p') {
  // 1. Strip self-closing deletion/move markers first (e.g. <w:del .../> in <w:rPr>)
  //    so they never pair up with a later closing </w:del> and swallow live paragraphs.
  const cleaned = String(xml)
    .replace(/<w:(?:del|delText|delInstrText|moveFrom)\b[^>]*\/>/g, '')
    .replace(/<w:del\b[^/>]*(?:\/(?!>)[^/>]*)*>[\s\S]*?<\/w:del>/g, '')
    .replace(/<w:delText\b[^/>]*(?:\/(?!>)[^/>]*)*>[\s\S]*?<\/w:delText>/g, '')
    .replace(/<w:delInstrText\b[^/>]*(?:\/(?!>)[^/>]*)*>[\s\S]*?<\/w:delInstrText>/g, '')
    .replace(/<w:moveFrom\b[^/>]*(?:\/(?!>)[^/>]*)*>[\s\S]*?<\/w:moveFrom>/g, '');
  const closeRe = new RegExp(`<\\/${blockTag}>`, 'g');
  const openRe = new RegExp(`<${blockTag}\\b[^>]*>`, 'g');
  const paras = [];
  for (const chunk of cleaned.split(closeRe)) {
    if (!openRe.test(chunk)) continue;
    openRe.lastIndex = 0;
    const inner = chunk
      .replace(/<w:tab\b[^>]*\/>/g, '\t')
      .replace(/<w:(?:br|cr)\b[^>]*\/>/g, ' ');
    const runs = [];
    for (const tm of inner.matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g)) {
      runs.push(decodeXmlEntities(tm[1]));
    }
    const text = runs.join('').trim();
    if (text) paras.push(text);
  }
  return paras;
}

/** Extract active text + tracked insertions + headers/footers + margin comments from a .docx file or Buffer. */
export function extractDocxText(pathOrBuffer) {
  const buf = Buffer.isBuffer(pathOrBuffer) ? pathOrBuffer : fs.readFileSync(pathOrBuffer);
  const entries = readZipEntries(buf);
  const sections = [];
  const docParts = [
    'word/document.xml',
    'word/footnotes.xml',
    'word/endnotes.xml',
    ...[...entries.keys()].filter((k) => /^word\/(?:header|footer)\d*\.xml$/i.test(k)).sort(),
  ];
  for (const part of docParts) {
    if (entries.has(part)) {
      const paras = xmlBlocksToParagraphs(entries.get(part).toString('utf8'), 'w:p');
      if (paras.length) sections.push(paras.join('\n\n'));
    }
  }
  if (entries.has('word/comments.xml')) {
    const comments = xmlBlocksToParagraphs(entries.get('word/comments.xml').toString('utf8'), 'w:comment');
    if (comments.length) sections.push(comments.map((c) => `[Comment] ${c}`).join('\n\n'));
  }
  return sections.join('\n\n');
}

/** Read a text/markdown or .docx file into a UTF-8 string for linting. */
export function readDocumentText(filePath) {
  if (/\.docx$/i.test(String(filePath))) return extractDocxText(filePath);
  return fs.readFileSync(filePath, 'utf8');
}

// ── PROPOSITION-LEVEL grounding (P2 2026-07-25 — the hardening the 07-25 review
// asked for). The substring check above proves only that the CITATION TOKEN appears
// somewhere in the pack — journal 0001's wrong-reporter cite (Powell: 148 T.C. 392,
// not 145 T.C. 411) is exactly the class it misses when a pack mentions both. The
// proposition check requires each citation's PARAGRAPH to carry a QUOTED SPAN
// ("..." / “...” , ≥ MIN_QUOTE_CHARS) that appears VERBATIM (whitespace-normalized)
// in a source — i.e. the memo shows the reader the words of the authority it leans
// on, and those words really are in the pack. [UNVERIFIED] on the line still exempts.

export const MIN_QUOTE_CHARS = 15;

function paragraphsOf(text) {
  const lines = String(text).split(/\r?\n/);
  const paras = [];
  let start = 0;
  for (let i = 0; i <= lines.length; i++) {
    if (i === lines.length || lines[i].trim() === '') {
      if (i > start) paras.push({ startLine: start + 1, endLine: i, text: lines.slice(start, i).join('\n') });
      start = i + 1;
    }
  }
  return paras;
}

function quotedSpans(text) {
  const spans = [];
  for (const m of String(text).matchAll(/["“]([^"”]{1,600}?)["”]/g)) {
    if (m[1].trim().length >= MIN_QUOTE_CHARS) spans.push(m[1].trim());
  }
  return spans;
}

/**
 * Proposition-level lint: for each citation, its enclosing paragraph must contain at
 * least one ≥15-char quoted span found verbatim (whitespace-normalized) in a source.
 * Returns { ok, checked, violations: [{citation, line, reason}] }.
 */
export function lintPropositions(findingsText, sourceTexts = []) {
  const sources = sourceTexts.map(norm);
  const paras = paragraphsOf(findingsText);
  const violations = [];
  let checked = 0;
  for (const c of extractCitations(findingsText)) {
    if (/\[unverified\b/i.test(c.lineText)) continue;
    checked += 1;
    const para = paras.find((p) => c.line >= p.startLine && c.line <= p.endLine);
    const spans = para ? quotedSpans(para.text) : [];
    if (!spans.length) {
      violations.push({ ...c, reason: `no quoted span (≥${MIN_QUOTE_CHARS} chars) in the citation's paragraph — quote the authority, then analyze` });
      continue;
    }
    const supported = spans.some((q) => sources.some((s) => s.includes(norm(q))));
    if (!supported) {
      violations.push({ ...c, reason: 'the paragraph quotes text that appears in NO provided source — the proposition is not grounded in the pack' });
    }
  }
  return { ok: violations.length === 0, checked, violations };
}

// ---- CLI ----
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const invokedDirectly = (() => {
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1] || ''); }
  catch { return false; }
})();
if (invokedDirectly) {
  const [findingsFile, ...sourceFiles] = process.argv.slice(2);
  if (!findingsFile || !sourceFiles.length) {
    console.error('usage: node src/citation-lint.js <findings-file(.md|.txt|.docx)> <source-file...>');
    process.exit(2);
  }
  const findings = readDocumentText(findingsFile);
  const sources = sourceFiles.map((f) => readDocumentText(f));
  const { ok, violations } = lintCitations(findings, sources);
  if (ok) {
    console.log(`citation-lint: CLEAN — every citation is grounded in the provided sources or tagged [UNVERIFIED].`);
    process.exit(0);
  }
  console.error(`citation-lint: ${violations.length} UNGROUNDED citation(s) — Rule 1 violation:`);
  for (const v of violations) {
    console.error(`  line ${v.line}: "${v.citation}" — not found in any provided source and not tagged [UNVERIFIED]`);
  }
  process.exit(1);
}

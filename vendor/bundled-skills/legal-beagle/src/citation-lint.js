// citation-lint.js — Rule 1 as STRUCTURE, not exhortation (W3, 2026-07-11).
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
//   rulings:         "PLR 200944002", "Rev. Rul. 2023-2"

import fs from 'node:fs';

const CITATION_RES = [
  /\b\d{1,4}\s+(?:U\.?S\.?|S\.?\s?Ct\.?|F\.(?:2d|3d|4th)|F\.?\s?Supp\.?(?:\s?\d?d?)?|P\.(?:2d|3d)|A\.(?:2d|3d))\s+\d{1,5}\b/g,
  /\b[A-Z][A-Za-z'’.-]+\s+v\.?\s+[A-Z][A-Za-z'’.-]+\b/g,
  /\b\d{1,3}\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s*§+\s*[\w.()-]+/g,
  /\b(?:[A-Z][a-z]+\s)?Code\s*(?:Ann\.?\s*)?§+\s*[\w.()-]+/g,
  /\bTreas\.?\s?Reg\.?\s*§+\s*[\w.()-]+/g,
  /\b(?:PLR|TAM)\s?\d{7,9}\b/g,
  /\bRev\.?\s?(?:Rul\.?|Proc\.?)\s?\d{2,4}-\d+\b/g,
];

const norm = (s) => String(s).replace(/[’]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase();

/** Extract citation-shaped strings with their line numbers. */
export function extractCitations(text) {
  const out = [];
  const lines = String(text).split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const re of CITATION_RES) {
      for (const m of line.matchAll(re)) {
        out.push({ citation: m[0].trim(), line: i + 1, lineText: line });
      }
    }
  });
  return out;
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
    const grounded = sources.some((s) => s.includes(norm(c.citation)));
    if (!grounded) violations.push(c);
  }
  return { ok: violations.length === 0, violations };
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
    console.error('usage: node src/citation-lint.js <findings-file> <source-file...>');
    process.exit(2);
  }
  const findings = fs.readFileSync(findingsFile, 'utf8');
  const sources = sourceFiles.map((f) => fs.readFileSync(f, 'utf8'));
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

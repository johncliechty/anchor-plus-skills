// legal-round engine + proposition-lint tests (2026-07-25). Hermetic — stub seats.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { lintPropositions, lintCitations, extractDocxText, readDocumentText, MIN_QUOTE_CHARS } from '../src/citation-lint.js';
import { buildLegalCharter, runLegalRound, loadSourcePack } from '../bin/legal-round.mjs';
import zlib from 'node:zlib';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SOURCE = [
  'Powell v. Commissioner, 148 T.C. 392 (2017). The court held that "the decedent retained',
  'the right, in conjunction with the partnership, to designate the persons who shall possess',
  'or enjoy the property" within the meaning of section 2036(a)(2).',
].join('\n');

test('proposition lint: quote-then-analyze PASSES when the paragraph quotes the pack verbatim', () => {
  const memo = [
    'Under Powell v. Commissioner, 148 T.C. 392, the manager risk is live: the court held that',
    '"the decedent retained the right, in conjunction with the partnership, to designate the',
    'persons who shall possess or enjoy the property".',
  ].join('\n');
  const r = lintPropositions(memo, [SOURCE]);
  assert.equal(r.ok, true, JSON.stringify(r.violations));
  assert.ok(r.checked >= 1);
});

test('proposition lint: a citation with NO quoted span fails — the journal-0001 wrong-cite class the substring check misses', () => {
  // Token-level lint PASSES here (the cite string appears in the pack) — that was the
  // hole: a claim ABOUT a real citation with no quoted support sailed through.
  const memo = 'Powell v. Commissioner, 148 T.C. 392 conclusively blesses manager appointments.';
  assert.equal(lintCitations(memo, [SOURCE]).ok, true, 'token lint alone is fooled — that is the documented gap');
  const r = lintPropositions(memo, [SOURCE]);
  assert.equal(r.ok, false);
  assert.match(r.violations[0].reason, /no quoted span/);
});

test('proposition lint: a quote that appears in NO source fails; [UNVERIFIED] exempts; short quotes do not count', () => {
  const fabricated = 'Powell v. Commissioner, 148 T.C. 392 says "manager appointments are always protected from 2036 inclusion".';
  const r1 = lintPropositions(fabricated, [SOURCE]);
  assert.equal(r1.ok, false);
  assert.match(r1.violations[0].reason, /appears in NO provided source/);
  const tagged = 'Powell v. Commissioner, 148 T.C. 392 [UNVERIFIED — memory cite, confirm before use].';
  assert.equal(lintPropositions(tagged, [SOURCE]).ok, true, 'the honest tag stays an exemption');
  const short = `Case v. Case, 100 U.S. 1 says "yes".`;
  const r2 = lintPropositions(short, ['Case v. Case, 100 U.S. 1 says yes indeed']);
  assert.equal(r2.ok, false, `a quote under ${MIN_QUOTE_CHARS} chars is not grounding`);
});

test('the charter names the journal-proven failure classes (jurisdiction, quote, PLR, certainty ceiling)', () => {
  const c = buildLegalCharter();
  for (const id of ['lb1', 'lb2', 'lb3', 'lb4', 'lb5']) assert.match(c, new RegExp(`\\[${id}\\]`));
  assert.match(c, /non-precedential/i);
  assert.match(c, /CONDITIONAL/);
});

function stubAgent({ blockedRounds = 0 } = {}) {
  return async (_prompt, opts = {}) => {
    const label = opts.label || '';
    if (label.startsWith('shark:')) {
      const round = Number((label.match(/:r(\d+)/) || [])[1] || 0);
      const role = label.split(':')[1];
      if (round <= blockedRounds && (role === 'Skeptic' || role === 'Contrarian')) {
        return { answerable: 'yes', findings: [{ severity: 'BLOCKER', topic: 'plr laundered as precedent',
          section: 'authority', tag: 'lb3', traces_to_north_star: 'yes', criterion: 'lb3',
          message: 'the only pro-taxpayer authority is a PLR presented without the non-precedential flag' }] };
      }
      return { answerable: 'yes', findings: [] };
    }
    if (label.startsWith('judge:')) return { decision: 'CONVERGED', reasons: ['dry + grounded'] };
    return {};
  };
}

const CLEAN_MEMO = [
  'Jurisdiction: U.S. federal tax (as of 2026-07-25).',
  '',
  'Powell v. Commissioner, 148 T.C. 392, is the controlling risk: the court held that',
  '"the decedent retained the right, in conjunction with the partnership, to designate the',
  'persons who shall possess or enjoy the property".',
].join('\n');

test('engine: gates-only mode (no agent) — deterministic gates run, review honestly does NOT', async () => {
  const rec = await runLegalRound({ memoText: CLEAN_MEMO, sourceTexts: [SOURCE], log: () => {} });
  assert.equal(rec.status, 'GATES-ONLY');
  assert.equal(rec.cross_model, false);
  assert.match(rec.verdict, /UNREVIEWED \(citation gates PASSED/);
});

test('engine: empty source pack fails CLOSED (journal 0006 rule)', async () => {
  await assert.rejects(() => runLegalRound({ memoText: CLEAN_MEMO, sourceTexts: [], log: () => {} }), /fail closed/);
});

test('engine: dry sharks + judge ⇒ GO with honest single-family stamp; a ≥2-agree blocker round records BLOCKED first', async () => {
  const go = await runLegalRound({ memoText: CLEAN_MEMO, sourceTexts: [SOURCE], agent: stubAgent(), rounds: 2, log: () => {} });
  assert.match(go.verdict, /^GO/);
  assert.equal(go.cross_model, false);
  assert.match(go.single_family_note, /cross_model:false honestly/);

  const held = await runLegalRound({ memoText: CLEAN_MEMO, sourceTexts: [SOURCE], agent: stubAgent({ blockedRounds: 1 }), rounds: 3, log: () => {} });
  assert.equal(held.rounds[0].verdict, 'BLOCKED');
  assert.ok(held.rounds[0].newBlockers[0].agreement >= 2);
  assert.equal(held.rounds.at(-1).dry, true);
});

test('engine: a FAILED citation gate blocks even a shark-dry review (the hard pre-delivery gate)', async () => {
  const bad = 'Smith v. Jones, 999 U.S. 999 settles this absolutely.';
  const rec = await runLegalRound({ memoText: bad, sourceTexts: [SOURCE], agent: stubAgent(), rounds: 1, log: () => {} });
  assert.match(rec.verdict, /BLOCKED \(citation gate FAILED\)/);
});

// Helper to build a minimal valid .docx zip buffer in-memory for testing Wave 2
function buildMiniDocxBuffer(filesMap) {
  const localParts = [];
  const cdParts = [];
  let offset = 0;
  for (const [name, contentStr] of Object.entries(filesMap)) {
    const nameBuf = Buffer.from(name, 'utf8');
    const rawBuf = Buffer.from(contentStr, 'utf8');
    const compBuf = zlib.deflateRawSync(rawBuf);
    const localHdr = Buffer.alloc(30);
    localHdr.writeUInt32LE(0x04034b50, 0);
    localHdr.writeUInt16LE(20, 4);
    localHdr.writeUInt16LE(8, 8); // deflate
    localHdr.writeUInt32LE(compBuf.length, 18);
    localHdr.writeUInt32LE(rawBuf.length, 22);
    localHdr.writeUInt16LE(nameBuf.length, 26);
    localParts.push(localHdr, nameBuf, compBuf);

    const cdHdr = Buffer.alloc(46);
    cdHdr.writeUInt32LE(0x02014b50, 0);
    cdHdr.writeUInt16LE(20, 4);
    cdHdr.writeUInt16LE(20, 6);
    cdHdr.writeUInt16LE(8, 10);
    cdHdr.writeUInt32LE(compBuf.length, 20);
    cdHdr.writeUInt32LE(rawBuf.length, 24);
    cdHdr.writeUInt16LE(nameBuf.length, 28);
    cdHdr.writeUInt32LE(offset, 42);
    cdParts.push(cdHdr, nameBuf);

    offset += localHdr.length + nameBuf.length + compBuf.length;
  }
  const cdBuf = Buffer.concat(cdParts);
  const count = Object.keys(filesMap).length;
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(count, 8);
  eocd.writeUInt16LE(count, 10);
  eocd.writeUInt32LE(cdBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, cdBuf, eocd]);
}

test('Wave 2 (.docx inspection): extracts body, <w:ins> tracked insertions, and comments while ignoring <w:del> deletions', async () => {
  const docXml = `<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:pPr><w:rPr><w:del w:id="0" w:author="Editor"/></w:rPr></w:pPr>
          <w:r><w:t>Qualified Person Trustee under </w:t></w:r>
          <w:del w:id="1"><w:r><w:delText>Utah Code § 75B-1-303(1)(c)</w:delText></w:r></w:del>
          <w:ins w:id="2"><w:r><w:t>Utah Code § 75B-1-303(2)(a)(ii)</w:t></w:r></w:ins>
          <w:r><w:t> ("at least one trustee is a Utah resident or Utah trust company").</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>Subsequent deleted run </w:t></w:r>
          <w:del w:id="3"><w:r><w:delText>old text</w:delText></w:r></w:del>
          <w:r><w:t> does not swallow the prior paragraph when a self-closing w:del is in w:rPr.</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>`;
  const commentsXml = `<?xml version="1.0" encoding="UTF-8"?>
    <w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:comment w:id="1">
        <w:p><w:r><w:t>Affidavit of solvency under Section 75B-1-306 ("the settlor shall sign a sworn affidavit").</w:t></w:r></w:p>
      </w:comment>
    </w:comments>`;
  const docxBuf = buildMiniDocxBuffer({
    'word/document.xml': docXml,
    'word/comments.xml': commentsXml,
  });
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-docx-'));
  const docxPath = path.join(tmpDir, 'redline.docx');
  const srcPath = path.join(tmpDir, 'utah-source.md');
  fs.writeFileSync(docxPath, docxBuf);
  fs.writeFileSync(srcPath, [
    'Utah Code § 75B-1-303(2)(a)(ii): "at least one trustee is a Utah resident or Utah trust company".',
    'Utah Code § 75B-1-306: "the settlor shall sign a sworn affidavit".',
  ].join('\n'), 'utf8');

  const extracted = readDocumentText(docxPath);
  assert.ok(extracted.includes('75B-1-303(2)(a)(ii)'), 'tracked insertion extracted');
  assert.ok(extracted.includes('Section 75B-1-306'), 'margin comment extracted');
  assert.ok(!extracted.includes('75B-1-303(1)(c)'), 'deleted tracked run stripped');

  const rec = await runLegalRound({
    memoText: extracted,
    sourceTexts: loadSourcePack([srcPath]).texts,
    log: () => {},
  });
  assert.equal(rec.citation_gate.token.ok, true);
  assert.equal(rec.citation_gate.proposition.ok, true);

  // Now inject an unverified citation inside a tracked insertion -> must fail
  const badDocxBuf = buildMiniDocxBuffer({
    'word/document.xml': docXml.replace('75B-1-303(2)(a)(ii)', '75B-1-303(1)(c)'),
  });
  const badText = extractDocxText(badDocxBuf);
  const badLint = lintCitations(badText, [fs.readFileSync(srcPath, 'utf8')]);
  assert.equal(badLint.ok, false, 'unverified citation in tracked insertion must fail');
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

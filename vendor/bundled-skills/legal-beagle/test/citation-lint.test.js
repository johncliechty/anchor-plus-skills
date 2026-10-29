// citation-lint.test.js — Rule 1 as structure (W3, 2026-07-11): a citation-shaped
// string in the output must be grounded in a provided source or tagged [UNVERIFIED].
import test from 'node:test';
import assert from 'node:assert';
import { extractCitations, lintCitations } from '../src/citation-lint.js';

const SOURCE = [
  'Utah Code § 75B-1-101 (recodified 2025). The trust instrument provides...',
  'Powell v. Commissioner, 148 T.C. 392; see also 26 U.S.C. § 2036(a).',
].join('\n');

test('extractCitations finds reporters, case names, statutes, and rulings', () => {
  const text = [
    'Under 26 U.S.C. § 2036(a) and Smith v. Jones, the retained-control issue...',
    'See PLR 200944002 and Rev. Rul. 2023-2; also 142 S. Ct. 2111.',
  ].join('\n');
  const found = extractCitations(text).map((c) => c.citation);
  assert.ok(found.some((c) => /2036/.test(c)), 'statute found');
  assert.ok(found.some((c) => /Smith v\.? Jones/.test(c)), 'case name found');
  assert.ok(found.some((c) => /PLR 200944002/.test(c)), 'PLR found');
  assert.ok(found.some((c) => /Rev\.? ?Rul\.? ?2023-2/.test(c)), 'Rev. Rul. found');
  assert.ok(found.some((c) => /142 S\.? ?Ct\.? 2111/.test(c)), 'reporter found');
});

test('grounded citations pass; a fabricated citation FAILS; [UNVERIFIED] tag passes honestly', () => {
  // grounded in SOURCE -> clean
  const good = 'The instrument cites Utah Code § 75B-1-101 and 26 U.S.C. § 2036(a).';
  assert.equal(lintCitations(good, [SOURCE]).ok, true);

  // fabricated (not in any source, untagged) -> violation. This is the sanctioned-
  // lawyer failure mode the rule exists for.
  const bad = 'As held in Varga v. Estate, 999 F.4th 1234, the transfer is excluded.';
  const r = lintCitations(bad, [SOURCE]);
  assert.equal(r.ok, false);
  assert.ok(r.violations.length >= 1);

  // the same fabricated cite, honestly tagged on its line -> passes the lint
  const tagged = 'As possibly held in Varga v. Estate, 999 F.4th 1234 [UNVERIFIED — do not rely on this citation].';
  assert.equal(lintCitations(tagged, [SOURCE]).ok, true, 'the honest tag is the sanctioned escape hatch');
});

test('no sources provided => every untagged citation is a violation (fail closed)', () => {
  const r = lintCitations('See Powell v. Commissioner, 148 T.C. 392.', []);
  assert.equal(r.ok, false, 'cannot ground against nothing — fail closed');
});

test('journal 0014 regression: standalone §, §§ multi-section lists, Section, IRC §, and formerly § are extracted and gated', () => {
  const utahPack = [
    'Effective 5/7/2025 75B-1-302. Governing law -- Restrictions on transfer of property.',
    'Effective 5/7/2025 75B-1-303. Requirements for asset protection trust -- § 75B-1-303(2)(a)(ii) Utah resident trustee or trust company under Section 7-5-1.',
    'Effective 5/7/2025 75B-1-304. Settlor powers -- § 75B-1-304(1) discretionary distributions.',
    'Effective 5/7/2025 75B-1-306. Affidavit of solvency.',
    'Effective 9/1/2024 75B-2-112 (formerly § 75-7-112, see also § 75-2-515). Penalty clause for contest.',
    'Effective 9/1/2024 75B-2-502 (formerly § 75-7-502). Spendthrift provision.',
    'Utah Code § 75-2-1203 (1,000-year statutory rule against perpetuities).',
    'Internal Revenue Code: IRC § 675(4)(C), § 672(a), § 2036(a)(2), § 2038.',
  ].join('\n');

  // 1. All four dreamed-up October 20 Utah Title 75B citations MUST fail closed when ungrounded
  for (const hallucinated of [
    'See § 75B-2-1104 (formerly § 75-2-1203) for the 1,000-year perpetuities period.',
    'Enforceable under § 75B-2-517 (formerly § 75-2-517) no-contest statute.',
    'Qualified Person Trustee under § 75B-1-303(1)(c) must be a Utah resident.',
    'Settlor must sign an Affidavit of Solvency under § 75B-1-303(1)(j).',
  ]) {
    const res = lintCitations(hallucinated, [utahPack]);
    assert.equal(res.ok, false, `must flag ungrounded citation in: ${hallucinated}`);
  }

  // 2. Multi-section §§ list: passes when every section is in the pack, fails when one is fabricated
  const goodList = 'Governed by §§ 75B-1-302, 75B-1-303, and 75B-1-304(1) and Section 75B-1-306 (with Section 7-5-1 and IRC § 675(4)(C)).';
  assert.equal(lintCitations(goodList, [utahPack]).ok, true);

  const poisonedList = 'Governed by §§ 75B-1-302, 75B-1-303, and 75B-2-1104.';
  const poisonedRes = lintCitations(poisonedList, [utahPack]);
  assert.equal(poisonedRes.ok, false, 'must flag fabricated 3rd item in §§ list');
  assert.ok(poisonedRes.violations.some((v) => /75B-2-1104/.test(v.citation)));

  // 3. Verified October 23 replacement citations pass cleanly
  const verifiedMemo = [
    'Asset protection under §§ 75B-1-302, 75B-1-303, and 75B-1-304(1), with Utah trustee under § 75B-1-303(2)(a)(ii) and Section 7-5-1.',
    'Affidavit of solvency required by Section 75B-1-306; spendthrift under § 75B-2-502 (formerly § 75-7-502).',
    '1,000-year perpetuities under Utah Code § 75-2-1203; no-contest under § 75B-2-112 (formerly § 75-7-112, see § 75-2-515).',
  ].join('\n');
  assert.equal(lintCitations(verifiedMemo, [utahPack]).ok, true);

  // 4. Cross-validation edge cases (dot-decimal suffix, wrong title, wrong state, short section)
  assert.equal(lintCitations('See § 31A-22-305.', ['Utah Code § 31A-22-305.3 uninsured motorist.']).ok, false, 'must not match .3 suffix');
  assert.equal(lintCitations('See 42 U.S.C. § 2503.', ['26 U.S.C. § 2503 taxable gifts.']).ok, false, 'must reject wrong federal title');
  assert.equal(lintCitations('See Idaho Code § 75-2-1203.', ['Utah Code § 75-2-1203 perpetuities.']).ok, false, 'must reject wrong state code');
  assert.equal(lintCitations('Gross income under § 61.', ['26 U.S.C. § 2503 taxable gifts.']).ok, false, 'must detect short standalone § 61');
});

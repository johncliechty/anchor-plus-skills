id: 0014-utah-title-75b-recodification-memory-hallucination
skill: legal-beagle@2026-10-23
situation: substituting recodified Utah Code Title 75B section and subsection numbers into trust drafts and counsel emails
context: Family Trusts, October 20–23 turns in session a9bb6909-4808-41c5-abd6-922faa39fa28
observation: On October 20, the steward agent substituted Utah Code Title 75B citations in-turn from model memory without fetching the official Utah Legislature text (le.utah.gov) into a source pack or running node bin/legal-round.mjs (lintCitations + lintPropositions). While Utah Code Title 75B, Chapter 1, Part 3 (§§ 75B-1-301 et seq.) and § 75B-2-502 (spendthrift) were real, four specific section/subsection citations were hallucinated from memory and caught by David Liechty: (1) § 75B-2-1104 for the 1,000-year Rule Against Perpetuities (does not exist; Title 75B, Ch. 2, Part 11 ends at § 75B-2-1103, and the 1,000-year rule remains in Title 75 at Utah Code § 75-2-1203, as Stanford originally wrote); (2) § 75B-2-517 for trust no-contest/penalty clauses (does not exist; 2-517 is the UPC model number, whereas Utah's trust penalty-clause statute is Utah Code § 75B-2-112, formerly § 75-7-112, and Utah's will statute is § 75-2-515); (3) § 75B-1-303(1)(c) for the Utah resident trustee/trust company requirement (actually § 75B-1-303(2)(a)(ii)); and (4) § 75B-1-303(1)(j) for the sworn Affidavit of Solvency (actually standalone section Utah Code § 75B-1-306). Fetching le.utah.gov via search_web into utah_code_source_pack.md and running node bin/legal-round.mjs verified all 17 statutory propositions cleanly (receipt 5d1fc668e876, sources a8d4a290ec7e).
outcome: fixed - all four Utah Code citations corrected across both trusts and the Stanford/David emails; verified via le.utah.gov source pack and bin/legal-round.mjs; hardening plan recorded below for another session to implement
provenance: genuine-execution

---

## Plain-English Summary (For John)

This journal entry explains why four inaccurate Utah law references slipped into the October 20 trust drafts and email to counsel, and lays out the concrete plan for a separate session to close those loopholes permanently. Once another session applies this plan, no legal email, memo, or Word redline will be able to ship with unverified law citations—whether the steward writes a Markdown memo or edits a Word document directly—because the citation checker will inspect Word files (including tracked changes and margin comments) and catch every section and subsection number automatically. Nothing further needs to run in the Family Trusts session; the plan below is ready to hand off whenever you open a hardening session.

---

## Root-Cause Diagnosis: Why `legal-beagle` Did Not Catch the Oct 20 Citations

1. **Steward Prompt Rule Collision ("DOCUMENTS in-turn" vs. Domain Skill Gate):**
   - Anchor's Steward prompt (`SIZE THE REQUEST FIRST (a)`) instructs the steward that *"DOCUMENTS and small non-code work — an answer, a note, a draft, a calendar file, an HTML or PDF page — you finish in this turn yourself."*
   - Meanwhile, `TASK CHALLENGE TRIAGE & CONTEXT SIZING (3)` lists the mandatory domain skills (`anvil`, `foreman`, `crucible`, `researchPrime`, `gandalf`, `einstein`, `ramanujan`)—omitting `legal-beagle` and `financial-analyst`.
   - As a result, on October 20 the steward treated the trust revisions and Stanford email as a routine in-turn document edit instead of a gated `legal-beagle` task, and never invoked `bin/legal-round.mjs`.

2. **Word (`.docx`) Blind Spot in `legal-round.mjs` and `foundry-tools`:**
   - `bin/legal-round.mjs` currently reads only UTF-8 Markdown/text files (`fs.readFileSync(memoPath, 'utf8')`).
   - When the steward builds or redlines `.docx` trust drafts via `ft.py docx-redline`, nothing checks the citations inside the `.docx` paragraphs, tracked insertions (`<w:ins>`), or margin comments (`<w:comment>`).

3. **Standalone Section / Subsection Regex Gap in `src/citation-lint.js`:**
   - Line 24 of `src/citation-lint.js` (`/\b(?:[A-Z][a-z]+\s)?Code\s*(?:Ann\.?\s*)?§+\s*[\w.()-]+/g`) only extracts a statutory citation when the word `Code` appears immediately before `§`.
   - Consequently, standalone section/subsection strings (`§ 75B-1-303(1)(c)`, `§ 75B-1-303(1)(j)`, `formerly § 75-2-1203`, `Section 75B-1-306`, `IRC § 675(4)(C)`) and the 2nd/3rd sections in multi-section lists (`§§ 75B-1-302, 75B-1-303, and 75B-1-304`) are invisible to `extractCitations`, `lintCitations`, and `lintPropositions`.

---

## Hardening Plan for Next Session (`Skill Foundry`, `foundry-tools`, and `Anchor`)

**What will be built:**
1. Expand `legal-beagle`'s citation extractor so every standalone `§`, `§§`, `Section`, `IRC §`, and `formerly §` reference (including comma/and-separated multi-section lists) is extracted and verified against the primary-source pack.
2. Add native `.docx` text/redline/comment extraction to `legal-beagle/bin/legal-round.mjs` so the gate runs directly on `.docx` files as well as `.md` files.
3. Add a statutory-citation gate hook in `foundry-tools/ft.py` (`docx-redline`) and a two-line rule update in `Anchor`'s Steward prompt so any legal document or `.docx` redline containing statutory/case citations cannot bypass `legal-round.mjs`.

**What is left out:**
- No LLM/model calls added to the fast deterministic gate (`gates-only` stays sub-second and zero-token).
- No changes to the Shark-Tank / Judge seat logic in `legal-round.mjs`.

**How we will know it works:**
- `node --test test/` in `<path> Foundry/skills/legal-beagle` passes with new regression tests covering the exact four October 20 Utah Title 75B failure cases (`§ 75B-2-1104`, `§ 75B-2-517`, `§ 75B-1-303(1)(c)`, `§ 75B-1-303(1)(j)`), standalone `formerly § ...` strings, comma-separated `§§` lists, and direct `.docx` redline inspection.

### Wave 1 — Harden `src/citation-lint.js` for Standalone `§`, `Section`, and Multi-Section Lists (`Skill Foundry`)
- **Files:** `<path> Foundry/skills/legal-beagle/src/citation-lint.js`, `<path> Foundry/skills/legal-beagle/test/citation-lint.test.js`
- **What it builds:**
  - Add regex rules to `CITATION_RES` (and post-match list expansion) for:
    - Standalone section symbols: `/§+\s*\d+[A-Za-z0-9.-]*(?:\([A-Za-z0-9]+\))*/g`
    - Multi-section lists after `§§`: e.g., `§§ 75B-1-302, 75B-1-303, and 75B-1-304` expands into three distinct citation tokens (`§ 75B-1-302`, `§ 75B-1-303`, `§ 75B-1-304`), each normalized so `Utah Code Ann. § 75B-1-303(2)(a)(ii)` or `§ 75B-1-303(2)(a)(ii)` matches against official statutory headings/subsections in the source pack.
    - `IRC § <num>` and `Section <title>-<ch>-<sec>` patterns (e.g., `Section 75B-1-306`, `Section 7-5-1`).
- **How it is tested:** `node --test "<path> Foundry/skills/legal-beagle/test/"` with unit tests proving all four October 20 dreamed-up citations fail closed when ungrounded and pass when grounded against `le.utah.gov` text.

### Wave 2 — Native `.docx` Support in `bin/legal-round.mjs` (`Skill Foundry`)
- **Files:** `<path> Foundry/skills/legal-beagle/bin/legal-round.mjs`, `<path> Foundry/skills/legal-beagle/test/legal-round.test.js`
- **What it builds:**
  - When `--memo` points to a `.docx` file, extract paragraph text (including `<w:ins>` tracked insertions and `word/comments.xml` margin comments, while ignoring `<w:del>` deleted text so removed erroneous citations do not trigger false positives) before running `lintCitations` and `lintPropositions`.
- **How it is tested:** `node --test "<path> Foundry/skills/legal-beagle/test/"` with a `.docx` fixture containing tracked changes and margin comments.

### Wave 3 — Steward Prompt & `ft.py docx-redline` Gate Integration (`Anchor` & `foundry-tools`)
- **Files:** Anchor steward prompt template (in `<path> and `<path>
- **What it builds:**
  - In `<path> Add `legal-beagle` and `financial-analyst` to `TASK CHALLENGE TRIAGE (3)` and add the 1-line exception in `SIZE THE REQUEST FIRST (a) DOCUMENTS` requiring `bin/legal-round.mjs` + primary-source pack before delivering any document or `.docx` that cites statutes, regulations, or cases.
  - In `<path> (`docx-redline`): Add `--sources <pack>` support (or an automatic citation warning/gate when statutory citations are detected in the output `.docx` without a verified source pack).
- **How it is tested:** Run `python <path> docx-redline --inspect` and existing `foundry-tools` tests.

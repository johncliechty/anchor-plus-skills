id: 0015-utah-title-75b-citation-lint-docx-and-cockpit-gate-hardening
skill: legal-beagle@2026-10-23
situation: implementing the 3-wave hardening plan from 0014 to close standalone statutory section/subsection regex gaps, native .docx inspection blind spots, and Steward Small-Duty gate bypasses
context: <path> Foundry\skills\legal-beagle, <path> and <path>
observation: Following the October 20–23 Utah Code Title 75B recodification citation failure documented in 0014, we implemented all three hardening waves across legal-beagle, foundry-tools (docx-redline), and Anchor's Steward prompt: (1) expanded src/citation-lint.js to extract standalone § / §§ section and subsection citations (including multi-section comma/and lists, 'formerly § ...', 'Section <title>-<ch>-<sec>', and 'IRC § <num>') and enforced exact token-boundary section/subsection matching in isCitationGrounded() so fabricated subsections like '§ 75B-1-303(1)(c)' fail closed even when '§ 75B-1-303(2)(a)(ii)' is in the source pack; (2) added zero-dependency native .docx ZIP/XML extraction (extractDocxText / readDocumentText) in src/citation-lint.js and wired bin/legal-round.mjs to inspect .docx files directly—including <w:ins> tracked insertions, footnotes, endnotes, and word/comments.xml margin comments while stripping <w:del>/<w:delText> deletions; (3) added --sources <pack> to <path> (which runs legal-round.mjs on the output .docx and fails closed on ungrounded citations) and updated Anchor's SMALL_DUTY prompt in steward_engine.py and FOUNDRY_SKILLS_SUMMARY in foundry_tools.py so 1–3 sentence legal/statutory or financial edits can never bypass legal-beagle or financial-analyst verification.
outcome: fixed - 13/13 Node tests in legal-beagle pass (node --test) and 6/6 integration tests in Anchor pass (pytest)
provenance: genuine-execution

---

## Plain-English Summary (For John)

All three loopholes identified after the Utah Code Title 75B incident are now closed and verified by automated regression tests:
1. **Standalone `§`, `§§`, `Section`, and `IRC §` citations are caught:** `src/citation-lint.js` now detects every standalone section and subsection reference (such as `§ 75B-1-303(1)(c)`, `§ 75B-1-303(1)(j)`, `formerly § 75-2-1203`, `Section 75B-1-306`, `IRC § 675(4)(C)`, and multi-section lists like `§§ 75B-1-302, 75B-1-303, and 75B-1-304(1)`) and verifies exact subsection boundaries against the primary-source pack.
2. **Direct `.docx` Word & redline inspection:** `legal-round.mjs` and `src/citation-lint.js` now read `.docx` files natively—checking body text, tracked insertions (`<w:ins>`), footnotes, endnotes, and margin comments (`word/comments.xml`) while ignoring deleted text (`<w:del>` / `<w:delText>`).
3. **`docx-redline --sources` & Steward Small-Duty gate:** `ft.py docx-redline` now accepts `--sources <pack>` to fail closed if any citation in a redlined `.docx` is ungrounded, and Anchor's Steward prompt (`steward_engine.py` + `foundry_tools.py`) explicitly exempts legal/statutory and financial edits from the Small-Duty rule so even a 1–3 sentence edit must pass `legal-round.mjs` or `verify_model.py`.

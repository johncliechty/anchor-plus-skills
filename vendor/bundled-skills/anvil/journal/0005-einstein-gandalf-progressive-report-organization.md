# 0005 — Codifying the Einstein + Gandalf Progressive Pedagogical Organization Standard for All Anvil Reports

**Date**: 2026-10-21
**Project**: Hierarchical Normalizing Flows (`Paper 1`)
**Skills Involved**: `anvil`, `einstein`, `gandalf`, `ramanujan`, `superjump`, `figure-designer`

## 1. Plain-English Summary

When we upgraded `ANVIL-REPORT.pdf` from a 34-line text stub to an illustrated report with 6 custom SVG figures (`Journal 0002`), the graphics made the architecture visible, but the report organization was still hard to follow because sections were reduced to dense italic figure captions without a progressive teaching arc. At John's direction, we combined **Einstein** and **Gandalf** to establish a mandatory **Progressive Pedagogical Report Standard** for all future Anvil reports, and codified that standard directly into `skills/anvil/SKILL.md`.

## 2. What Made the Caption-Only Organization Hard to Follow

1. **Missing Story Roadmap**: The report jumped straight into internal Anvil vocabulary (`Orange-Split`, `Juice / Peel / Pith`, `Bucket 1 / 2 / 3`) without a 60-second reader's guide explaining how the sections fit together.
2. **Caption-Heavy, Narrative-Light Sections**: During review streamlining, explanatory paragraphs had been compressed into 150-word italic figure captions packed with JSON line numbers and file paths.
3. **Missing Toy Examples Before High-Dimensional Math**: Readers were shown $p = 3{,}002$ and $p = 50{,}002$ Jacobian structures before seeing a 3-variable worked toy example.

## 3. The Mandatory Einstein + Gandalf Anvil Report Organization (Codified in `SKILL.md`)

Every human-facing `ANVIL-REPORT.md` / `ANVIL-REPORT.pdf` must follow this 5-part progressive pedagogical structure:
1. **Plain-English Opening & 60-Second Reader's Roadmap Table**: Open with 3–4 non-programmer sentences (what the software does, what the audit found, what decision if any is needed), followed immediately by a compact table mapping the reader's core questions to Sections 1–6 and Figures 1–6.
2. **Einstein 4-Block Pedagogical Structure Inside Every Section**:
   - **Block A — The Core Question & Plain-English Intuition**: 2–3 jargon-free sentences explaining what this section answers and why it matters.
   - **Block B — Concrete Miniature Worked Example**: A small, self-contained 2- or 3-variable example (with explicit numbers) illustrating the mechanism before scaling up.
   - **Block C — Custom Vector Figure (`figures/anvil/fig*.svg`)**: A multi-panel SVG diagram designed with `figure-designer` (`>= 9.5px` typography, exact coordinate scaling, zero text collisions).
   - **Block D — Exact Verified Codebase Evidence & One-Line Takeaway**: The exact file paths, line spans, and function counts verified against `.anvil/session.json`, ending with a bold one-sentence takeaway.

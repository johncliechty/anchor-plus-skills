# ANVIL — Locked North Star & Idea Log

**Skill Path:** `<path> Foundry\skills\anvil\`  
**Date Locked:** 2026-10-14  
**Author & Convergence Authority:** John  
**Visual Brand Asset:** `/vendor/brand/workbench-anvil.jpg` + Standard Anchor Mark (`/vendor/brand/anchor-tab-48.png`)

---

## 1. The Locked North Star (Exact Text)

> **ANVIL NORTH STAR (2026-10-14 — Rev 3)**
>
> **Mission:** `Anvil` is the human-centered code comprehension, empirical validation, best-in-class re-architecture, and paper-to-software verification skill. Instead of overwhelming the human with raw AST dumps or noisy call graphs, `Anvil` organizes code and research implementations around **human understanding**, **persistent interactive dialogue across every page**, **live execution proof**, and **adversarially reviewed old-to-new and paper-to-software process equivalence**.
>
> **Four Core Pillars + Cross-Cutting Persistent Dialogue:**
>
> 1. **Human-Oriented Top-Level Mapping (`anvil map` — Conceptual Groupings vs. Process Map + AI Agent Touchpoints):**
>    - Provides a clean top-level toggle between **Conceptual Groupings** (human-meaningful functional buckets and summaries of functions inside each block) and a **Process Map** (how each block of code interacts with the rest of the blocks of code).
>    - Explicitly highlights **where AI agents interact with the system and in what way** (e.g., CLI/sub-agent dispatch, prompt/context assembly, tool calls, file/state mutations, or adversarial review gates).
>
> 2. **Focused Block Drill-Down & Live Claim Testing (`anvil inspect`):**
>    - Clicking any block of code opens **just that block** in an isolated drill-down view showing:
>      - Its inner parts as an **Inner Process Map** alongside concise summaries of its functions and clickable links to the actual source code.
>      - A clear plain-English statement of **how the code is supposed to work** (its claimed contract).
>      - **Live Execution Validation:** `Anvil` runs the block's code against real/representative inputs to test whether what the summary says it does matches what the code actually does in practice, and stamps the block as **`✓ Validated`**—rolling all validated block descriptions up into a human-readable **Anvil Report** (`ANVIL-REPORT.md`).
>
> 3. **Best-in-Class Code Remapping, Old-to-New Process Bridge & Explicit `∅ Null Space` (`anvil remap`):**
>    - For new or refactored best-in-class code, provides the same **Conceptual Bucket Summary** and **Process Map** with full drill-down into the inner workings and actual source code, backed by live execution runs and **cross-family adversarial reviews**.
>    - Provides a visual **Old-to-New Process Map** showing exactly where every block and function of the old code lives in the new code's process map—paired with an explicit **`∅ Null Space`** panel right next to the new code map listing old functionality that does not exist in the new code (distinguishing intentional retirement of dead/Frankenstein bloat from accidental regressions, which fail closed).
>    - Empirically and adversarially validates that the new code delivers the end-to-end pipeline functionality it claims across three mandatory stages: **(1) Getting the Data (`INGEST`), (2) Doing the Analysis (`COMPUTE / ANALYZE`), and (3) Creating the Output (`EMIT`)**.
>
> 4. **Paper-to-Software Process Mapping, Typeset Mathematical Tie-In & Empirical/Adversarial Validation (`anvil paper-map`):**
>    - Renders a full **Software Process Map** for the codebase that claims to implement a research paper, showing how the software blocks interact end-to-end and **how each part of the paper—especially every mathematical equation, theorem, objective function, and algorithm—ties directly into the different blocks and functions of the software**.
>    - **Native Typeset Mathematics (Zero Raw LaTeX):** All equations, fractions, summations, and mathematical symbols are rendered in clean typeset mathematical notation (MathML / typeset HTML math, never raw `$...$` LaTeX source strings) alongside a **Variable-by-Variable Math-to-Code Tie-In Matrix** mapping paper equations and symbols to exact software blocks, functions, line ranges, and code tensors/variables.
>    - Runs **live empirical numerical verification + cross-family adversarial validation** on each mathematical tie-in to test whether the software actually computes what the paper claims (catching silent approximations, dropped normalization terms, mismatched equations, or hardcoded shortcuts), and feeds directly into `anvil remap` to refactor research prototypes into best-in-class production code.
>
> 5. **Persistent Interactive Anvil Agent Dialogue Across All 4 Pages/Modes:**
>    - Every page of the `Anvil` workbench (`1. Conceptual & Process Map`, `2. Block Drill-Down & Live Probe`, `3. Old-to-New Map & ∅ Null Space`, and `4. Paper-to-Software Process & Math Map`) features a **persistent right-side Anvil Agent Dialogue Dock** synced to the active mode and selected block/equation so the human can ask questions, clarify math or code, refine summaries, and lock validated descriptions from any tab.

---

## 2. John's Idea Log (Attached to `Anvil` — 2026-10-14)

| ID | Requirement / Idea | Where It Lives in `Anvil` |
| :--- | :--- | :--- |
| **ANV-01** | Orient for **human understanding** rather than overwhelming detail; toggle between **Conceptual Groupings** and a **Process Map** of how each block interacts with the rest. | Mode 1 (`anvil map`) — Dual-view toggle (`Conceptual Buckets` ⇄ `System Process Map`) |
| **ANV-02** | Show **where AI agents interact and in what way** across the blocks of code. | Mode 1 (`anvil map`) — `🤖 AI Agent Interaction Overlay` badges & interaction contracts |
| **ANV-03** | Within a block of code, show a summary of functions; clicking a block opens **just that block** and shows its inner parts as an **Inner Process Map** + statement of **how the code is supposed to work**. | Mode 2 (`anvil inspect`) — Isolated Single-Block Inspector + Inner Process Map |
| **ANV-04** | Ability for `Anvil` to **run the code and test whether what the summary says it does matches what it actually does**. | Mode 2 (`anvil inspect`) — `▶ Run & Verify Claim vs. Actual` empirical probe runner |
| **ANV-05** | **Interactive dialogue with the Anvil agent** to ask questions, clarify/refine what is going on, and lock a **`Validated` description** that rolls up into an **Anvil Report**. | All 4 Modes — Persistent Right-Side `Anvil Agent Dialogue Dock` + `✓ Lock Validated Description` → `ANVIL-REPORT.md` |
| **ANV-06** | Map to **new best-in-class code** with both a **Conceptual Bucket Summary** and a **Process Map**, with drill-down into inner workings and actual code + validation & **adversarial reviews**. | Mode 3 (`anvil remap`) — Target Architecture Process Map + Drill-Down + Cross-Family Adversarial Review |
| **ANV-07** | **Old-to-New Process Map** showing where old code functionality exists in the new code process map, with an explicit **`∅ Null Space`** next to the new code map for old functionality that does not exist in the new code. | Mode 3 (`anvil remap`) — Visual Old-to-New Bridge + `∅ Null Space (Intentional Drops vs. Unmapped Alerts)` |
| **ANV-08** | Validate (with live runs + adversarial reviews) that the new code has the functionality it claims: **getting the data, doing the analysis, and creating the output as claimed**. | Mode 3 (`anvil remap`) — 3-Stage End-to-End Pipeline Gate (`1. Get Data` → `2. Do Analysis` → `3. Create Output`) |
| **ANV-09** | **Paper-to-Software Process Map & Mathematical Tie-In (`anvil paper-map`):** Include a full **Software Process Map** for the paper's code and show in detail how the paper—**especially all math, equations, symbols, and derivations from the paper**—ties into the different parts of the software, verified by empirical runs + adversarial review, then refactored into production code. | Mode 4 (`anvil paper-map`) — Software Process Map with Paper Math Tie-In Callouts + Variable-by-Variable Equation ↔ Code Matrix + Empirical/Adversarial Verifier |
| **ANV-10** | **Persistent Anvil Dialogue Window on All Pages:** Keep the interactive `Anvil` dialogue window visible and context-aware across **all 4 pages/tabs**, not just inside a single block drill-down. | All 4 Modes — Right-side `aside.anvil-dialogue-dock` with live context pill (`Mode 1..4`) and quick-prompt chips |
| **ANV-11** | **Rendered Typeset Mathematics (No Raw LaTeX):** Render all mathematical formulas on the Paper-to-Software Process & Math Map in **actual typeset mathematical notation** (proper fractions, summations, integrals, subscripts/superscripts) rather than raw `$...$` LaTeX source code. | Mode 4 (`anvil paper-map`) — Native `<math>` MathML + mathematical typography across both the Process Map callouts and the Variable-by-Variable Equation Matrix |

# 0006 — Anvil v2: 3-Level Progressive Process Map, Live Polyglot Code Walkthrough, and 5-Seat Software Beta-Reader Panel

- **Date:** 2026-10-21
- **Skill:** `Anvil` (`<path> Foundry\skills\anvil`)
- **Author:** Antigravity (`Gemini 3.1 Pro (High)`) with independent cross-family adversarial review by `Claude Fable 5.1` (`claude.exe`)
- **Status:** SHIPPED & VERIFIED

## Context & Problem Statement
In Anvil v1, users had to switch between four separate tabs (`1. Conceptual & Process Map`, `2. Single-Block Drill-Down`, `3. Old -> New Code Map & Null Space`, and `4. Paper <-> Code`) to understand how a block's high-level purpose connected to its internal equations, assumptions, refactoring diff, and actual source lines. In addition, John requested:
1. **Progressive In-Place Expansion** on the Process Map (`Level 1: Role & I/O` $\to$ `Level 2: Sub-flow, Native MathML Equations, Explicit Assumptions & Old-to-New Diff` $\to$ `Level 3: Full Numbered Source Code`).
2. **Live Polyglot Code Walkthrough (`▶ Walkthrough Code`)** that steps through the codebase section-by-section, showing **Claimed Behavior**, **Concrete Input Data**, **Actual Runtime Calculation & Output**, and an honest **Accuracy Verdict (`ACCURATE` | `DRIFT` | `MISMATCH`)**.
3. **5-Seat Software Beta-Reader Panel** (inspired by Chekhov's beta readers and grounded in Cal Newport's cognitive-load reduction, John Ousterhout's Deep Modules, and Gary Bernhardt's Functional Core / Imperative Shell).

## Key Changes Implemented
1. **`scripts/anvil_engine.py`**:
   - Added `_enrich_progressive_levels()` populating `level1_summary`, `level2_mechanics` (with `sub_blocks`, `formulas_mathml`, `assumptions`, and `old_to_new_diff`), and `level3_code` on every conceptual and module bucket.
   - Added `run_code_walkthrough()` and CLI subcommand `walkthrough` / flag `--walkthrough` for live section-by-section execution and AST/runtime claim verification.
   - Added `run_beta_reader_panel()` and CLI subcommand `beta-readers` implementing the 5 specialist seats (`cal_newport_cognitive_load`, `functional_core_architect`, `numerical_verification_auditor`, `systems_performance_specialist`, `security_boundary_auditor`).
   - Added `render_markdown_report()` and CLI subcommand `render-report` producing self-contained Markdown reports with inline SVGs, the 5-Seat Beta-Reader table, and the Block-by-Block Walkthrough table.
2. **Anchor AI Cockpit Integration (`steward_cockpit/anvil_session.py`, `steward_routes.py`, `static/anvil.html`, `static/v1.html`, `static/shared.js`)**:
   - Added `walkthrough_in_session()` and `/api/anvil/walkthrough` (plus `POST /api/steward/anvil` with `action: "walkthrough"`).
   - Upgraded `static/anvil.html` and the embedded Anvil workbench in `static/v1.html` / `static/shared.js` with the **`▶ Walkthrough Code`** interactive stepper, 3-Level Progressive Expansion cards on Process Map nodes, and the Software Beta-Reader Panel strip.
